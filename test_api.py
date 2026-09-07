import unittest

from fastapi.testclient import TestClient

from backend.app.main import app


def _deterministic_gpx(point_count: int = 30) -> bytes:
    points = "".join(
        f'<trkpt lat="0" lon="{index * 0.0001:.7f}"><ele>0</ele></trkpt>'
        for index in range(point_count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" creator="api-test" version="1.1">'
        f'<trk><name>Deterministic Route</name><trkseg>{points}</trkseg></trk>'
        '</gpx>'
    ).encode("utf-8")


class APITests(unittest.TestCase):
    client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_cors_allows_only_frontend_development_origins(self):
        request_headers = {"Access-Control-Request-Method": "GET"}
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = self.client.options(
                "/api/routes",
                headers={"Origin": origin, **request_headers},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], origin)
            self.assertNotIn("access-control-allow-credentials", response.headers)

        response = self.client.options(
            "/api/routes",
            headers={"Origin": "http://example.com", **request_headers},
        )
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_valid_gpx_returns_exact_public_contract(self):
        response = self.client.post(
            "/api/routes/analyze",
            files={"file": (r"C:\\client\\route.gpx", _deterministic_gpx(), "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        expected_fields = {
            "filename",
            "track_name",
            "point_count",
            "segment_count",
            "raw_3d_ecef_polyline_length_m",
            "corrected_distance_m",
            "fractal_dimension",
            "r_squared",
        }
        self.assertEqual(set(payload), expected_fields)
        self.assertEqual(payload["filename"], "route.gpx")
        self.assertEqual(payload["track_name"], "Deterministic Route")
        self.assertIs(type(payload["point_count"]), int)
        self.assertIs(type(payload["segment_count"]), int)
        for field in (
            "raw_3d_ecef_polyline_length_m",
            "corrected_distance_m",
            "fractal_dimension",
            "r_squared",
        ):
            self.assertIs(type(payload[field]), float)
        self.assertEqual(
            payload["corrected_distance_m"],
            payload["raw_3d_ecef_polyline_length_m"],
        )

    def test_malformed_gpx_returns_422(self):
        response = self.client.post(
            "/api/routes/analyze",
            files={"file": ("broken.gpx", b"<gpx><broken>", "application/gpx+xml")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Cannot parse GPX stream", response.json()["detail"])

    def test_non_gpx_filename_is_rejected(self):
        response = self.client.post(
            "/api/routes/analyze",
            files={"file": ("route.txt", _deterministic_gpx(), "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "The uploaded file must have a .gpx filename.",
        )


if __name__ == "__main__":
    unittest.main()
