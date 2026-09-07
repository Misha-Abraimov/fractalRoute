import math
import tempfile
import unittest
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path

from fractal_route import (
    AnalysisConfig,
    AnalysisResult,
    GPXData,
    ScaleMeasurement,
    TrackPoint,
    WGS84_A_M,
    WGS84_F,
    analyze_gpx_data,
    calculate_corrected_distance,
    fit_log_log,
    geodetic_to_ecef,
    measure_at_scale,
    parse_gpx,
    parse_gpx_stream,
    richardson_measurements,
)


class CoordinateTests(unittest.TestCase):
    def test_equator_prime_meridian(self):
        x, y, z = geodetic_to_ecef(TrackPoint(0.0, 0.0, 0.0))
        self.assertAlmostEqual(x, WGS84_A_M, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_north_pole(self):
        x, y, z = geodetic_to_ecef(TrackPoint(90.0, 0.0, 0.0))
        expected_b = WGS84_A_M * (1.0 - WGS84_F)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, expected_b, places=6)

    def test_corrected_distance_policy_preserves_distance(self):
        self.assertEqual(calculate_corrected_distance(6341.897949), 6341.897949)


class SkippingTests(unittest.TestCase):
    def test_threshold_skip_discards_endpoint_remainder(self):
        line = [[(float(x), 0.0, 0.0) for x in range(11)]]
        result = measure_at_scale(line, 3.0)
        self.assertEqual(result.retained_points, 4)
        self.assertEqual(result.measured_links, 3)
        self.assertAlmostEqual(result.length_m, 9.0)
        self.assertAlmostEqual(result.min_link_m, 3.0)

    def test_recursive_threshold_uses_previous_actual_average(self):
        line = [[(float(x), 0.0, 0.0) for x in range(11)]]
        results = richardson_measurements(line, multiplier=2.0, maximum_measurements=3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].kind, "raw")
        self.assertAlmostEqual(results[0].scale_m, 1.0)
        self.assertAlmostEqual(results[1].threshold_m, 2.0)
        self.assertAlmostEqual(results[1].scale_m, 2.0)
        self.assertAlmostEqual(results[2].threshold_m, 4.0)
        self.assertAlmostEqual(results[2].length_m, 8.0)

    def test_separate_segments_are_not_connected(self):
        segments = [[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [(100.0, 0.0, 0.0), (103.0, 0.0, 0.0)]]
        result = measure_at_scale(segments, 1.0)
        self.assertAlmostEqual(result.length_m, 5.0)


class RegressionTests(unittest.TestCase):
    def test_known_dimension(self):
        measurements = []
        for scale in (1.0, 2.0, 4.0, 8.0):
            length = 4.0 * scale ** -0.25
            item = ScaleMeasurement(
                pass_number=0,
                kind="test",
                threshold_m=scale,
                scale_m=scale,
                length_m=length,
                retained_points=20,
                measured_links=19,
                mean_link_m=scale,
                standard_deviation_m=0.0,
                min_link_m=scale,
                max_link_m=scale,
            )
            measurements.append(replace(item, used_in_fit=True))
        fit = fit_log_log(measurements)
        self.assertAlmostEqual(fit.slope, -0.25)
        self.assertAlmostEqual(fit.intercept, math.log(4.0))
        self.assertAlmostEqual(fit.fractal_dimension, 1.25)
        self.assertAlmostEqual(fit.r_squared, 1.0)


class ParserTests(unittest.TestCase):
    def test_namespaced_gpx_and_missing_elevation(self):
        xml = """<?xml version="1.0"?>
        <gpx xmlns="http://www.topografix.com/GPX/1/1" creator="test" version="1.1">
          <trk><name>tiny</name><trkseg>
            <trkpt lat="1" lon="2"><ele>3</ele><time>2025-01-01T00:00:00Z</time></trkpt>
            <trkpt lat="1.1" lon="2.1"/>
          </trkseg></trk>
        </gpx>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.gpx"
            path.write_text(xml, encoding="utf-8")
            result = parse_gpx(path)
        self.assertEqual(result.creator, "test")
        self.assertEqual(result.track_name, "tiny")
        self.assertEqual(len(result.segments[0]), 2)
        self.assertEqual(result.segments[0][1].elevation_m, 0.0)

    def test_parse_gpx_stream_accepts_in_memory_binary_stream(self):
        xml = b"""<?xml version="1.0"?>
        <gpx xmlns="http://www.topografix.com/GPX/1/1" creator="stream-test" version="1.1">
          <trk><name>memory</name><trkseg>
            <trkpt lat="29.0" lon="-82.0"><ele>4</ele></trkpt>
            <trkpt lat="29.0001" lon="-82.0"><ele>5</ele></trkpt>
          </trkseg></trk>
        </gpx>"""
        result = parse_gpx_stream(BytesIO(xml))
        self.assertIsInstance(result, GPXData)
        self.assertEqual(result.creator, "stream-test")
        self.assertEqual(result.track_name, "memory")
        self.assertEqual(len(result.segments[0]), 2)


class ReusableAnalysisTests(unittest.TestCase):
    def test_analysis_result_has_api_ready_summary_for_cross_platform_source_paths(self):
        points = [TrackPoint(0.0, index * 0.0001, 0.0) for index in range(10)]
        data = GPXData(
            segments=[points],
            creator="test",
            version="1.1",
            track_name="deterministic",
            metadata_time=None,
            exercise_info={},
        )
        for source_name in (
            r"C:\private\deterministic.gpx",
            "/private/deterministic.gpx",
        ):
            with self.subTest(source_name=source_name):
                result = analyze_gpx_data(
                    data,
                    AnalysisConfig(num_scales=3),
                    source_name=source_name,
                )

                self.assertIsInstance(result, AnalysisResult)
                for key in (
                    "corrected_distance_m",
                    "raw_track",
                    "measurements",
                    "linear_fit",
                    "gpx",
                ):
                    self.assertIn(key, result.summary)
                self.assertEqual(
                    result.summary["corrected_distance_m"],
                    result.summary["raw_track"]["ecef_polyline_length_m"],
                )
                self.assertEqual(result.summary["source_name"], "deterministic.gpx")
                self.assertEqual(
                    result.summary["measurements"],
                    [asdict(item) for item in result.measurements],
                )


if __name__ == "__main__":
    unittest.main()
