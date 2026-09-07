import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import Route
from backend.app.routes import get_job_services_factory
from tests.aws_fakes import FakeJobServices


def _segmented_gpx(points_per_segment: int = 30) -> bytes:
    def segment(latitude: float, initial_longitude: float) -> str:
        points = "".join(
            f'<trkpt lat="{latitude}" lon="{initial_longitude + index * 0.0001:.7f}"><ele>0</ele></trkpt>'
            for index in range(points_per_segment)
        )
        return f"<trkseg>{points}</trkseg>"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" creator="persistence-test" version="1.1">'
        f'<trk><name>Two Segment Route</name>{segment(0.0, 0.0)}{segment(1.0, 1.0)}</trk>'
        '</gpx>'
    ).encode("utf-8")


def _single_point_gpx() -> bytes:
    return b"""<?xml version="1.0"?>
    <gpx xmlns="http://www.topografix.com/GPX/1/1" creator="failure-test" version="1.1">
      <trk><name>Too Short</name><trkseg><trkpt lat="0" lon="0"/></trkseg></trk>
    </gpx>"""


class PersistenceAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(cls.temp_directory.name) / "routes.sqlite3"
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

        def override_get_db():
            database = cls.session_factory()
            try:
                yield database
            finally:
                database.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.job_services = FakeJobServices()
        app.dependency_overrides[get_job_services_factory] = lambda: lambda: cls.job_services
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_job_services_factory, None)
        cls.engine.dispose()
        cls.temp_directory.cleanup()

    def setUp(self):
        self.job_services.reset()
        with self.session_factory() as database:
            database.execute(delete(Route))
            database.commit()

    def test_create_queues_source_and_returns_frontend_compatible_route(self):
        source = _segmented_gpx()
        response = self.client.post(
            "/api/routes",
            files={"file": (r"C:\\client\\two-segments.gpx", source, "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertFalse(response.history)
        route = response.json()
        UUID(route["id"])
        self.assertEqual(route["filename"], "two-segments.gpx")
        self.assertIsNone(route["track_name"])
        self.assertEqual(route["status"], "queued")
        self.assertIsNone(route["point_count"])
        self.assertIsNone(route["segment_count"])
        self.assertIsNone(route["completed_at"])
        self.assertIsNone(route["error_message"])
        self.assertIsNone(route["corrected_distance_m"])
        self.assertIsNone(route["geometry"])

        expected_key = f"routes/{route['id']}/original.gpx"
        self.assertEqual(self.job_services.objects[expected_key], source)
        self.assertEqual(
            self.job_services.jobs,
            [{"route_id": route["id"], "s3_key": expected_key}],
        )
        serialized_job = json.dumps(self.job_services.jobs[0])
        self.assertNotIn("<gpx", serialized_job)
        self.assertNotIn("trkpt", serialized_job)

        retrieved = self.client.get(f"/api/routes/{route['id']}")
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json(), route)

        listed = self.client.get("/api/routes")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()], [route["id"]])

        with self.session_factory() as database:
            stored = database.get(Route, route["id"])
            stored_count = database.scalar(select(func.count()).select_from(Route))
            self.assertEqual(stored.source_object_key, expected_key)
        self.assertEqual(stored_count, 1)

    def test_route_row_is_committed_before_job_is_published(self):
        observed_rows: list[tuple[str | None, str | None]] = []

        def observe_route_at_publish_time(route_id: str, object_key: str) -> None:
            with self.session_factory() as observer:
                route = observer.get(Route, route_id)
                observed_rows.append(
                    (
                        route.status if route is not None else None,
                        route.source_object_key if route is not None else None,
                    )
                )

        self.job_services.on_enqueue = observe_route_at_publish_time

        response = self.client.post(
            "/api/routes",
            files={"file": ("route.gpx", _segmented_gpx(), "application/gpx+xml")},
        )

        self.assertEqual(response.status_code, 202, response.text)
        route_id = response.json()["id"]
        self.assertEqual(
            observed_rows,
            [("queued", f"routes/{route_id}/original.gpx")],
        )

    def test_stateless_analysis_endpoint_does_not_create_a_row(self):
        response = self.client.post(
            "/api/routes/analyze",
            files={"file": ("stateless.gpx", _segmented_gpx(), "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        listed = self.client.get("/api/routes")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [])
        self.assertEqual(self.job_services.jobs, [])

    def test_nonexistent_route_returns_404(self):
        response = self.client.get("/api/routes/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Route not found.")

    def test_persistent_upload_defers_malformed_gpx_validation_to_worker(self):
        malformed = b"<gpx><broken>"
        response = self.client.post(
            "/api/routes",
            files={"file": ("broken.gpx", malformed, "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 202)
        route = response.json()
        self.assertEqual(route["status"], "queued")
        object_key = f"routes/{route['id']}/original.gpx"
        self.assertEqual(self.job_services.objects[object_key], malformed)

    def test_aws_enqueue_failure_is_persisted_without_sdk_details(self):
        self.job_services.fail_enqueue = True
        response = self.client.post(
            "/api/routes",
            files={"file": ("route.gpx", _segmented_gpx(), "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "The route could not be queued for analysis. Please try again.",
        )
        listed = self.client.get("/api/routes")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        failed = listed.json()[0]
        self.assertEqual(failed["status"], "failed")
        self.assertNotIn("Fake SQS", failed["error_message"])
        self.assertIsNotNone(failed["completed_at"])

    def test_aws_upload_failure_is_persisted_without_enqueuing(self):
        self.job_services.fail_upload = True
        response = self.client.post(
            "/api/routes",
            files={"file": ("route.gpx", _segmented_gpx(), "application/gpx+xml")},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.job_services.jobs, [])
        listed = self.client.get("/api/routes").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["status"], "failed")
        self.assertNotIn("Fake S3", listed[0]["error_message"])


if __name__ == "__main__":
    unittest.main()
