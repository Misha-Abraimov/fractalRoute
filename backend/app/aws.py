"""Small, replaceable S3 and SQS boundary for asynchronous route jobs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO, Mapping, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class AWSConfigurationError(RuntimeError):
    """Raised when required application-level AWS settings are absent."""


class AWSServiceError(RuntimeError):
    """Raised for retryable failures at the AWS SDK boundary."""


@dataclass(frozen=True)
class AWSSettings:
    region: str
    bucket: str
    queue_url: str

    @classmethod
    def from_environment(cls) -> AWSSettings:
        values: dict[str, str] = {}
        for name in (
            "AWS_REGION",
            "FRACTAL_ROUTE_S3_BUCKET",
            "FRACTAL_ROUTE_SQS_QUEUE_URL",
        ):
            value = os.environ.get(name, "").strip()
            if not value:
                raise AWSConfigurationError(f"{name} is required.")
            values[name] = value
        return cls(
            region=values["AWS_REGION"],
            bucket=values["FRACTAL_ROUTE_S3_BUCKET"],
            queue_url=values["FRACTAL_ROUTE_SQS_QUEUE_URL"],
        )


class JobServices(Protocol):
    def upload_route_source(self, source: BinaryIO, object_key: str) -> None: ...

    def enqueue_route_job(self, route_id: str, object_key: str) -> None: ...

    def download_route_source(self, object_key: str) -> BinaryIO: ...

    def receive_messages(self) -> list[Mapping[str, object]]: ...

    def delete_message(self, receipt_handle: str) -> None: ...


def route_source_object_key(route_id: str) -> str:
    return f"routes/{route_id}/original.gpx"


class BotoJobServices:
    """Boto3 implementation that relies on the normal credential provider chain."""

    def __init__(self, settings: AWSSettings) -> None:
        self.settings = settings
        session = boto3.Session(region_name=settings.region)
        self._s3 = session.client("s3")
        self._sqs = session.client("sqs")

    def upload_route_source(self, source: BinaryIO, object_key: str) -> None:
        try:
            source.seek(0)
            self._s3.upload_fileobj(
                source,
                self.settings.bucket,
                object_key,
                ExtraArgs={"ContentType": "application/gpx+xml"},
            )
        except (BotoCoreError, ClientError) as exc:
            raise AWSServiceError("S3 upload failed.") from exc

    def enqueue_route_job(self, route_id: str, object_key: str) -> None:
        body = json.dumps(
            {"route_id": route_id, "s3_key": object_key},
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            self._sqs.send_message(QueueUrl=self.settings.queue_url, MessageBody=body)
        except (BotoCoreError, ClientError) as exc:
            raise AWSServiceError("SQS enqueue failed.") from exc

    def download_route_source(self, object_key: str) -> BinaryIO:
        destination = BytesIO()
        try:
            self._s3.download_fileobj(
                self.settings.bucket,
                object_key,
                destination,
            )
        except (BotoCoreError, ClientError) as exc:
            raise AWSServiceError("S3 download failed.") from exc
        destination.seek(0)
        return destination

    def receive_messages(self) -> list[Mapping[str, object]]:
        try:
            response = self._sqs.receive_message(
                QueueUrl=self.settings.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=10,
                MessageSystemAttributeNames=[
                    "SentTimestamp",
                    "ApproximateReceiveCount",
                ],
            )
        except (BotoCoreError, ClientError) as exc:
            raise AWSServiceError("SQS receive failed.") from exc
        messages = response.get("Messages", [])
        return list(messages) if isinstance(messages, list) else []

    def delete_message(self, receipt_handle: str) -> None:
        try:
            self._sqs.delete_message(
                QueueUrl=self.settings.queue_url,
                ReceiptHandle=receipt_handle,
            )
        except (BotoCoreError, ClientError) as exc:
            raise AWSServiceError("SQS delete failed.") from exc


def create_job_services() -> JobServices:
    return BotoJobServices(AWSSettings.from_environment())
