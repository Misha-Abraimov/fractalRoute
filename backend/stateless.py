"""Pure, in-memory route analysis adapter for synchronous API entry points."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import ntpath

from backend.app.geometry import gpx_data_to_geojson
from fractal_route import AnalysisConfig, analyze_gpx_data, parse_gpx_stream


MAX_GPX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_GPX_UPLOAD_MESSAGE = "GPX files must be 4 MiB or smaller."


@dataclass(frozen=True)
class StatelessRouteAnalysis:
    filename: str
    track_name: str | None
    point_count: int
    segment_count: int
    raw_3d_ecef_polyline_length_m: float
    corrected_distance_m: float
    fractal_dimension: float
    r_squared: float
    geometry: dict[str, object]


def normalize_gpx_filename(source_name: str | None) -> str:
    """Return a safe filename for Windows- or POSIX-style upload names."""

    filename = ntpath.basename(source_name or "")
    if not filename or not filename.lower().endswith(".gpx"):
        raise ValueError("Upload a file with a .gpx extension.")
    return filename


def analyze_gpx_bytes(
    contents: bytes,
    source_name: str | None,
    config: AnalysisConfig | None = None,
) -> StatelessRouteAnalysis:
    """Analyze GPX bytes without filesystem, database, or cloud dependencies."""

    if len(contents) > MAX_GPX_UPLOAD_BYTES:
        raise OverflowError(MAX_GPX_UPLOAD_MESSAGE)

    filename = normalize_gpx_filename(source_name)
    gpx_data = parse_gpx_stream(BytesIO(contents))
    result = analyze_gpx_data(gpx_data, config or AnalysisConfig(), source_name=filename)
    summary = result.summary
    gpx = summary["gpx"]
    raw_track = summary["raw_track"]
    linear_fit = summary["linear_fit"]

    return StatelessRouteAnalysis(
        filename=filename,
        track_name=gpx["track_name"],
        point_count=gpx["point_count"],
        segment_count=gpx["segment_count"],
        raw_3d_ecef_polyline_length_m=raw_track["ecef_polyline_length_m"],
        corrected_distance_m=summary["corrected_distance_m"],
        fractal_dimension=linear_fit["fractal_dimension"],
        r_squared=linear_fit["r_squared"],
        geometry=gpx_data_to_geojson(gpx_data),
    )
