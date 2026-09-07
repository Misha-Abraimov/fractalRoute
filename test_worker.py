import json
import tempfile
import unittest
from pathlib import Path
from threading import Event

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.aws import AWSServiceError, route_source_object_key
from backend.app.database import Base
from backend.app.models import Route
from backend.worker import process_queue_message, run_worker
from test_persistence import _segmented_gpx, _single_point_gpx
from tests.aws_fakes import FakeJobServices


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(cls.temp_directory.name) / "worker.sqlite3"
        cls.engine = create_engine(
            f"sqlite+pysqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        cls.session_factory = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp_directory.cleanup()

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.job_services = FakeJobServices()

    def queue_route(self, source: bytes, *, status: str = "queued") -> tuple[str, dict[str, object]]:
        with self.session_factory() as database:
            route = Route(filename="worker-test.gpx", status=status)
            database.add(route)
            database.flush()
            route.source_object_key = route_source_object_key(route.id)
            database.commit()
            route_id = route.id
            object_key = route.source_object_key

        self.job_services.objects[object_key] = source
        self.job_services.enqueue_route_job(route_id, object_key)
        return route_id, self.job_services.messages[0]

    def test_worker_transitions_to_completed_and_populates_results(self):
        route_id, message = self.queue_route(_segmented_gpx())
        message["Attributes"]["ApproximateReceiveCount"] = "3"
        observed_statuses: list[str] = []

        def observe_processing_commit():
            with self.session_factory() as observer:
                observed_statuses.append(observer.get(Route, route_id).status)

        self.job_services.on_download = observe_processing_commit
        with self.assertLogs("backend.worker", level="INFO") as captured_logs:
            with self.session_factory() as database:
                result = process_queue_message(message, database, self.job_services)

        self.assertEqual(result, "completed")
        self.assertEqual(observed_statuses, ["processing"])
        self.assertEqual(self.job_services.deleted_receipts, ["receipt-1"])
        with self.session_factory() as database:
            route = database.get(Route, route_id)
            self.assertEqual(route.status, "completed")
            self.assertEqual(route.track_name, "Two Segment Route")
            self.assertEqual(route.point_count, 60)
            self.assertEqual(route.segment_count, 2)
            self.assertIsNotNone(route.raw_3d_ecef_polyline_length_m)
            self.assertEqual(
                route.corrected_distance_m,
                route.raw_3d_ecef_polyline_length_m,
            )
            self.assertIsNotNone(route.fractal_dimension)
            self.assertIsNotNone(route.r_squared)
            self.assertEqual(route.geometry["type"], "MultiLineString")
            self.assertEqual(len(route.geometry["coordinates"]), 2)
            self.assertIsNotNone(route.completed_at)
            self.assertEqual(route.receive_count, 3)
            self.assertGreaterEqual(route.queue_wait_ms, 0.0)
            self.assertGreaterEqual(route.analysis_duration_ms, 0.0)
            self.assertGreaterEqual(route.total_duration_ms, route.analysis_duration_ms)

        benchmark = json.loads(captured_logs.records[-1].getMessage())
        self.assertEqual(benchmark["event"], "route_job_completed")
        self.assertEqual(benchmark["route_id"], route_id)
        self.assertEqual(benchmark["status"], "completed")
        self.assertEqual(benchmark["point_count"], 60)
        self.assertEqual(benchmark["receive_count"], 3)
        self.assertGreaterEqual(benchmark["queue_wait_ms"], 0.0)
        self.assertGreaterEqual(benchmark["analysis_duration_ms"], 0.0)
        self.assertGreaterEqual(
            benchmark["total_duration_ms"], benchmark["analysis_duration_ms"]
        )

    def test_retryable_download_failure_does_not_delete_message(self):
        route_id, message = self.queue_route(_segmented_gpx())
        self.job_services.fail_download = True

        with self.session_factory() as database:
            with self.assertRaises(AWSServiceError):
                process_queue_message(message, database, self.job_services)

        self.assertEqual(self.job_services.deleted_receipts, [])
        with self.session_factory() as database:
            self.assertEqual(database.get(Route, route_id).status, "processing")

    def test_retryable_failure_logs_exception_type_message_and_traceback(self):
        _, message = self.queue_route(_segmented_gpx())
        self.job_services.fail_download = True
        stop_requested = Event()
        receive_count = 0

        def receive_once():
            nonlocal receive_count
            receive_count += 1
            if receive_count == 1:
                return [message]
            stop_requested.set()
            return []

        self.job_services.receive_messages = receive_once

        with self.assertLogs("backend.worker", level="WARNING") as captured:
            run_worker(self.job_services, self.session_factory, stop_requested)

        failures = [
            record
            for record in captured.records
            if "will return to the queue" in record.getMessage()
        ]
        self.assertEqual(len(failures), 1)
        self.assertIn("AWSServiceError", failures[0].getMessage())
        self.assertIn("Fake S3 download failure.", failures[0].getMessage())
        self.assertIsNotNone(failures[0].exc_info)
        self.assertIn("Traceback", "\n".join(captured.output))
        self.assertEqual(self.job_services.deleted_receipts, [])

    def test_duplicate_completed_delivery_is_acknowledged_without_analysis(self):
        route_id, message = self.queue_route(_segmented_gpx(), status="completed")

        with self.session_factory() as database:
            result = process_queue_message(message, database, self.job_services)

        self.assertEqual(result, "duplicate")
        self.assertEqual(self.job_services.download_count, 0)
        self.assertEqual(self.job_services.deleted_receipts, ["receipt-1"])
        with self.session_factory() as database:
            self.assertEqual(database.get(Route, route_id).status, "completed")

    def test_permanent_analysis_failure_is_persisted_and_acknowledged(self):
        route_id, message = self.queue_route(_single_point_gpx())

        with self.session_factory() as database:
            result = process_queue_message(message, database, self.job_services)

        self.assertEqual(result, "failed")
        self.assertEqual(self.job_services.deleted_receipts, ["receipt-1"])
        with self.session_factory() as database:
            route = database.get(Route, route_id)
            self.assertEqual(route.status, "failed")
            self.assertIn("at least two distinct points", route.error_message)
            self.assertIsNotNone(route.completed_at)


if __name__ == "__main__":
    unittest.main()
