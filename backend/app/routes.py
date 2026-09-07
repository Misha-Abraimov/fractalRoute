"""HTTP routes that adapt requests to the reusable analysis library."""

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from fractal_route import AnalysisConfig, analyze_gpx_data, parse_gpx_stream

from .aws import (
    AWSConfigurationError,
    AWSServiceError,
    JobServices,
    create_job_services,
    route_source_object_key,
)
from .database import get_db
from .models import Route
from .schemas import RouteAnalysisResponse, StoredRouteResponse


router = APIRouter(prefix="/api/routes", tags=["routes"])


JobServicesFactory = Callable[[], JobServices]


def get_job_services_factory() -> JobServicesFactory:
    return create_job_services


def _safe_upload_filename(filename: str) -> str:
    """Remove either POSIX or Windows client-side path components."""
    return PurePosixPath(filename.replace("\\", "/")).name


def _validated_upload_filename(file: UploadFile) -> str:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An uploaded filename is required.",
        )
    filename = _safe_upload_filename(file.filename)
    if not filename.lower().endswith(".gpx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file must have a .gpx filename.",
        )
    return filename


def _persist_submission_failure(
    database: Session,
    *,
    route_id: str,
    filename: str,
    object_key: str,
) -> None:
    """Persist the same safe failure state before or after the initial commit."""

    database.rollback()
    route = database.get(Route, route_id)
    if route is None:
        route = Route(id=route_id, filename=filename)
        database.add(route)
    route.status = "failed"
    route.source_object_key = object_key
    route.error_message = "The route could not be stored or queued for analysis."
    route.completed_at = datetime.now(timezone.utc)
    database.commit()


@router.post(
    "/analyze",
    response_model=RouteAnalysisResponse,
    summary="Analyze a GPX route synchronously",
)
def analyze_route(file: UploadFile = File(...)) -> RouteAnalysisResponse:
    filename = _validated_upload_filename(file)

    try:
        file.file.seek(0)
        data = parse_gpx_stream(file.file)
        result = analyze_gpx_data(data, AnalysisConfig(), source_name=filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    summary = result.summary
    gpx = summary["gpx"]
    raw_track = summary["raw_track"]
    linear_fit = summary["linear_fit"]
    return RouteAnalysisResponse(
        filename=filename,
        track_name=gpx["track_name"],
        point_count=gpx["point_count"],
        segment_count=gpx["segment_count"],
        raw_3d_ecef_polyline_length_m=raw_track["ecef_polyline_length_m"],
        corrected_distance_m=summary["corrected_distance_m"],
        fractal_dimension=linear_fit["fractal_dimension"],
        r_squared=linear_fit["r_squared"],
    )


@router.post(
    "",
    response_model=StoredRouteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload and queue a GPX route",
)
def create_route(
    file: UploadFile = File(...),
    database: Session = Depends(get_db),
    job_services_factory: JobServicesFactory = Depends(get_job_services_factory),
) -> Route:
    filename = _validated_upload_filename(file)
    try:
        job_services = job_services_factory()
    except AWSConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Asynchronous route processing is not configured.",
        ) from exc
    route = Route(filename=filename, status="queued")
    database.add(route)
    database.flush()
    object_key = route_source_object_key(route.id)
    route.source_object_key = object_key

    try:
        file.file.seek(0)
        job_services.upload_route_source(file.file, object_key)
    except AWSServiceError as exc:
        _persist_submission_failure(
            database,
            route_id=route.id,
            filename=filename,
            object_key=object_key,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The route could not be queued for analysis. Please try again.",
        ) from exc

    # The worker has its own database session. Commit the row before publishing
    # its ID so an immediate SQS delivery can always resolve the route.
    database.commit()

    try:
        job_services.enqueue_route_job(route.id, object_key)
    except AWSServiceError as exc:
        _persist_submission_failure(
            database,
            route_id=route.id,
            filename=filename,
            object_key=object_key,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The route could not be queued for analysis. Please try again.",
        ) from exc

    database.refresh(route)
    return route


@router.get("", response_model=list[StoredRouteResponse], summary="List saved routes")
def list_routes(database: Session = Depends(get_db)) -> list[Route]:
    statement = select(Route).order_by(Route.created_at.desc())
    return list(database.scalars(statement).all())


@router.get(
    "/{route_id}",
    response_model=StoredRouteResponse,
    summary="Get a saved route",
)
def get_route(route_id: str, database: Session = Depends(get_db)) -> Route:
    try:
        normalized_id = str(UUID(route_id))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")
    route = database.get(Route, normalized_id)
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")
    return route
