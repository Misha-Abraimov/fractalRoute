import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.index import app
from backend.app.config import get_allowed_origins
from backend.stateless import MAX_GPX_UPLOAD_BYTES


def _deterministic_gpx(point_count: int = 30) -> bytes:
    points = "".join(
        f'<trkpt lat="0" lon="{index * 0.0001:.7f}"><ele>0</ele></trkpt>'
        for index in range(point_count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" creator="vercel-test" version="1.1">'
        f'<trk><name>Public Route</name><trkseg>{points}</trkseg></trk>'
        '</gpx>'
    ).encode("utf-8")


class VercelAPITests(unittest.TestCase):
    client = TestClient(app)

    def test_health_requires_no_environment_configuration(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_entrypoint_imports_with_cloud_and_database_variables_unset(self):
        environment = os.environ.copy()
        for name in (
            "DATABASE_URL",
            "AWS_PROFILE",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_REGION",
            "FRACTAL_ROUTE_S3_BUCKET",
            "FRACTAL_ROUTE_SQS_QUEUE_URL",
            "ALLOWED_ORIGINS",
        ):
            environment.pop(name, None)
        environment["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
        completed = subprocess.run(
            [sys.executable, "-c", "import api.index; print(api.index.app.title)"],
            cwd=os.getcwd(),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Fractal Route Public API", completed.stdout)

    def test_valid_analysis_uses_no_aws_and_returns_public_result(self):
        with (
            patch("boto3.client", side_effect=AssertionError("AWS must not be called")),
            patch("boto3.resource", side_effect=AssertionError("AWS must not be called")),
        ):
            response = self.client.post(
                "/api/routes/analyze",
                files={
                    "file": (
                        r"C:\client\public-route.gpx",
                        _deterministic_gpx(),
                        "application/gpx+xml",
                    )
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {
                "filename",
                "track_name",
                "point_count",
                "segment_count",
                "corrected_distance_m",
                "fractal_dimension",
                "r_squared",
                "geometry",
            },
        )
        self.assertEqual(payload["filename"], "public-route.gpx")
        self.assertGreater(payload["corrected_distance_m"], 0)
        self.assertEqual(payload["geometry"]["type"], "MultiLineString")
        self.assertEqual(len(payload["geometry"]["coordinates"][0]), 30)

    def test_malformed_gpx_returns_422(self):
        response = self.client.post(
            "/api/routes/analyze",
            files={"file": ("broken.gpx", b"<gpx><broken>", "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Cannot parse GPX stream", response.json()["detail"])

    def test_oversized_gpx_is_rejected(self):
        response = self.client.post(
            "/api/routes/analyze",
            files={
                "file": (
                    "large.gpx",
                    b"x" * (MAX_GPX_UPLOAD_BYTES + 1),
                    "application/gpx+xml",
                )
            },
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "GPX files must be 4 MB or smaller.")

    def test_allowed_origins_adds_configured_production_origins(self):
        with patch.dict(
            os.environ,
            {"ALLOWED_ORIGINS": "https://fractal-route.example, https://preview.example/"},
        ):
            origins = get_allowed_origins()
        self.assertIn("http://localhost:5173", origins)
        self.assertIn("http://127.0.0.1:5173", origins)
        self.assertIn("https://fractal-route.example", origins)
        self.assertIn("https://preview.example", origins)
        self.assertNotIn("*", origins)


if __name__ == "__main__":
    unittest.main()
