"""In-memory AWS boundary used by API and worker tests."""

from __future__ import annotations

import json
from io import BytesIO
from time import time
from typing import BinaryIO, Callable, Mapping

from backend.app.aws import AWSServiceError


class FakeJobServices:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.jobs: list[dict[str, str]] = []
        self.messages: list[dict[str, object]] = []
        self.deleted_receipts: list[str] = []
        self.download_count = 0
        self.fail_upload = False
        self.fail_enqueue = False
        self.fail_download = False
        self.on_download: Callable[[], None] | None = None
        self.on_enqueue: Callable[[str, str], None] | None = None

    def reset(self) -> None:
        self.__init__()

    def upload_route_source(self, source: BinaryIO, object_key: str) -> None:
        if self.fail_upload:
            raise AWSServiceError("Fake S3 upload failure.")
        source.seek(0)
        self.objects[object_key] = source.read()

    def enqueue_route_job(self, route_id: str, object_key: str) -> None:
        if self.fail_enqueue:
            raise AWSServiceError("Fake SQS enqueue failure.")
        if self.on_enqueue is not None:
            self.on_enqueue(route_id, object_key)
        payload = {"route_id": route_id, "s3_key": object_key}
        self.jobs.append(payload)
        self.messages.append(
            {
                "Body": json.dumps(payload),
                "ReceiptHandle": f"receipt-{len(self.messages) + 1}",
                "Attributes": {
                    "SentTimestamp": str(int(time() * 1000)),
                    "ApproximateReceiveCount": "1",
                },
            }
        )

    def download_route_source(self, object_key: str) -> BinaryIO:
        self.download_count += 1
        if self.on_download is not None:
            self.on_download()
        if self.fail_download:
            raise AWSServiceError("Fake S3 download failure.")
        return BytesIO(self.objects[object_key])

    def receive_messages(self) -> list[Mapping[str, object]]:
        return list(self.messages)

    def delete_message(self, receipt_handle: str) -> None:
        self.deleted_receipts.append(receipt_handle)
