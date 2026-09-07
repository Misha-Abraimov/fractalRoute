"""Standalone SQS worker for persisted route analysis jobs."""

from __future__ import annotations

import json
import logging
import signal
from datetime import datetime, timezone
from threading import Event
from time import perf_counter, time
from typing import Literal, Mapping
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from fractal_route import AnalysisConfig, analyze_gpx_data, parse_gpx_stream

from .app.aws import AWSServiceError, JobServices, create_job_services
from .app.database import get_session_factory, initialize_database
from .app.geometry import gpx_data_to_geojson
from .app.models import Route


LOGGER = logging.getLogger(__name__)
ProcessResult = Literal["completed", "failed", "duplicate", "discarded"]


class InvalidJobMessage(ValueError):
    """A message cannot identify a valid route job and must not be retried."""


class RetryableJobError(RuntimeError):
    """A valid message cannot be processed yet and should become visible again."""


def _message_benchmark_metadata(
    message: Mapping[str, object],
) -> tuple[int | None, float | None]:
    attributes = message.get("Attributes")
    if not isinstance(attributes, Mapping):
        return None, None

    receive_count: int | None = None
    queue_wait_ms: float | None = None
    raw_receive_count = attributes.get("ApproximateReceiveCount")
    raw_sent_timestamp = attributes.get("SentTimestamp")
    try:
        if raw_receive_count is not None:
            receive_count = max(1, int(str(raw_receive_count)))
    except ValueError:
        pass
    try:
        if raw_sent_timestamp is not None:
            queue_wait_ms = max(0.0, time() * 1000.0 - float(str(raw_sent_timestamp)))
    except ValueError:
        pass
    return receive_count, queue_wait_ms


def _duration_ms(started_at: float) -> float:
    return max(0.0, (perf_counter() - started_at) * 1000.0)


def _log_benchmark(
    *,
    route_id: str,
    status: ProcessResult,
    point_count: int | None,
    receive_count: int | None,
    queue_wait_ms: float | None,
    analysis_duration_ms: float | None,
    total_duration_ms: float,
) -> None:
    LOGGER.info(
        json.dumps(
            {
                "event": "route_job_completed",
                "route_id": route_id,
                "status": status,
                "point_count": point_count,
                "receive_count": receive_count,
                "queue_wait_ms": queue_wait_ms,
                "analysis_duration_ms": analysis_duration_ms,
                "total_duration_ms": total_duration_ms,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _message_receipt(message: Mapping[str, object]) -> str:
    receipt_handle = message.get("ReceiptHandle")
    if not isinstance(receipt_handle, str) or not receipt_handle:
        raise InvalidJobMessage("The SQS message has no receipt handle.")
    return receipt_handle


def _job_payload(message: Mapping[str, object]) -> tuple[str, str]:
    body = message.get("Body")
    if not isinstance(body, str):
        raise InvalidJobMessage("The SQS message body must be a string.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise InvalidJobMessage("The SQS message body is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise InvalidJobMessage("The SQS message body must be an object.")

    route_id = payload.get("route_id")
    object_key = payload.get("s3_key")
    if not isinstance(route_id, str) or not isinstance(object_key, str):
        raise InvalidJobMessage("The route_id and s3_key must be strings.")
    try:
        route_id = str(UUID(route_id))
    except ValueError as exc:
        raise InvalidJobMessage("The route_id is not a valid UUID.") from exc
    if object_key != f"routes/{route_id}/original.gpx":
        raise InvalidJobMessage("The S3 object key does not match the route ID.")
    return route_id, object_key


def process_queue_message(
    message: Mapping[str, object],
    database: Session,
    job_services: JobServices,
) -> ProcessResult:
    """Process one delivery, deleting it only after a terminal durable outcome."""

    job_started_at = perf_counter()
    receive_count, queue_wait_ms = _message_benchmark_metadata(message)
    receipt_handle = _message_receipt(message)
    try:
        route_id, object_key = _job_payload(message)
    except InvalidJobMessage:
        job_services.delete_message(receipt_handle)
        return "discarded"

    route = database.get(Route, route_id)
    if route is None:
        raise RetryableJobError("The route row is not available yet.")
    if route.source_object_key != object_key:
        job_services.delete_message(receipt_handle)
        return "discarded"
    if route.status in {"completed", "failed"}:
        job_services.delete_message(receipt_handle)
        _log_benchmark(
            route_id=route_id,
            status="duplicate",
            point_count=route.point_count,
            receive_count=receive_count,
            queue_wait_ms=queue_wait_ms,
            analysis_duration_ms=None,
            total_duration_ms=_duration_ms(job_started_at),
        )
        return "duplicate"

    route.status = "processing"
    route.error_message = None
    route.receive_count = receive_count
    route.queue_wait_ms = queue_wait_ms
    database.commit()

    analysis_started_at = perf_counter()
    try:
        with job_services.download_route_source(object_key) as source:
            data = parse_gpx_stream(source)
        result = analyze_gpx_data(data, AnalysisConfig(), source_name=route.filename)
    except ValueError as exc:
        analysis_duration_ms = _duration_ms(analysis_started_at)
        route.status = "failed"
        route.error_message = str(exc)
        route.completed_at = datetime.now(timezone.utc)
        route.analysis_duration_ms = analysis_duration_ms
        route.total_duration_ms = _duration_ms(job_started_at)
        database.commit()
        job_services.delete_message(receipt_handle)
        _log_benchmark(
            route_id=route_id,
            status="failed",
            point_count=route.point_count,
            receive_count=receive_count,
            queue_wait_ms=queue_wait_ms,
            analysis_duration_ms=analysis_duration_ms,
            total_duration_ms=_duration_ms(job_started_at),
        )
        return "failed"

    summary = result.summary
    gpx = summary["gpx"]
    raw_track = summary["raw_track"]
    linear_fit = summary["linear_fit"]
    route.track_name = gpx["track_name"]
    route.point_count = gpx["point_count"]
    route.segment_count = gpx["segment_count"]
    route.raw_3d_ecef_polyline_length_m = raw_track["ecef_polyline_length_m"]
    route.corrected_distance_m = summary["corrected_distance_m"]
    route.fractal_dimension = linear_fit["fractal_dimension"]
    route.r_squared = linear_fit["r_squared"]
    route.geometry = gpx_data_to_geojson(data)
    analysis_duration_ms = _duration_ms(analysis_started_at)
    route.status = "completed"
    route.completed_at = datetime.now(timezone.utc)
    route.analysis_duration_ms = analysis_duration_ms
    route.total_duration_ms = _duration_ms(job_started_at)
    database.commit()
    job_services.delete_message(receipt_handle)
    _log_benchmark(
        route_id=route_id,
        status="completed",
        point_count=route.point_count,
        receive_count=receive_count,
        queue_wait_ms=queue_wait_ms,
        analysis_duration_ms=analysis_duration_ms,
        total_duration_ms=_duration_ms(job_started_at),
    )
    return "completed"


def run_worker(
    job_services: JobServices,
    session_factory: sessionmaker[Session],
    stop_requested: Event,
) -> None:
    LOGGER.info("Route analysis worker started.")
    while not stop_requested.is_set():
        try:
            messages = job_services.receive_messages()
        except AWSServiceError as exc:
            LOGGER.exception(
                "Could not receive SQS messages (%s): %s; retrying shortly.",
                type(exc).__name__,
                exc,
            )
            stop_requested.wait(5)
            continue

        for message in messages:
            if stop_requested.is_set():
                break
            with session_factory() as database:
                try:
                    result = process_queue_message(message, database, job_services)
                except (AWSServiceError, RetryableJobError) as exc:
                    database.rollback()
                    LOGGER.exception(
                        "A route job could not be completed (%s): %s; "
                        "it will return to the queue.",
                        type(exc).__name__,
                        exc,
                    )
                else:
                    LOGGER.info("Route job finished with outcome: %s", result)
    LOGGER.info("Route analysis worker stopped.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop_requested = Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s; stopping after current work.", signum)
        stop_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    initialize_database()
    run_worker(create_job_services(), get_session_factory(), stop_requested)


if __name__ == "__main__":
    main()
