#!/usr/bin/env python3
"""Analyze a GPX track's corrected distance and Richardson fractal dimension.

The implementation intentionally uses only Python's standard library.
Coordinates are converted from WGS-84 geodetic latitude, longitude and height
to Earth-Centred, Earth-Fixed (ECEF) XYZ coordinates before distances are
measured.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import ntpath
import statistics
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import BinaryIO, Iterable, Sequence, TextIO


WGS84_A_M = 6_378_137.0
WGS84_F = 1.0 / 298.257_223_563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


@dataclass(frozen=True)
class TrackPoint:
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    time: datetime | None = None


@dataclass
class GPXData:
    segments: list[list[TrackPoint]]
    creator: str | None
    version: str | None
    track_name: str | None
    metadata_time: str | None
    exercise_info: dict[str, float | str]


@dataclass(frozen=True)
class ScaleMeasurement:
    pass_number: int
    kind: str
    threshold_m: float | None
    scale_m: float
    length_m: float
    retained_points: int
    measured_links: int
    mean_link_m: float
    standard_deviation_m: float
    min_link_m: float
    max_link_m: float
    used_in_fit: bool = False


@dataclass(frozen=True)
class LinearFit:
    slope: float
    intercept: float
    r_squared: float
    fractal_dimension: float
    point_count: int


@dataclass(frozen=True)
class AnalysisConfig:
    min_scale_m: float | None = None
    max_scale_m: float | None = None
    scale_factor: float = 1.5
    num_scales: int = 14
    explicit_scales_m: tuple[float, ...] | None = None
    min_retained_points: int = 2


@dataclass
class AnalysisResult:
    data: GPXData
    xyz_segments: list[list[tuple[float, float, float]]]
    measurements: list[ScaleMeasurement]
    fit: LinearFit
    summary: dict[str, object]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_gpx_stream(stream: BinaryIO | TextIO) -> GPXData:
    """Parse GPX track data from an open binary or text stream."""
    try:
        root = ET.parse(stream).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"Cannot parse GPX stream: {exc}") from exc

    segments: list[list[TrackPoint]] = []
    track_name: str | None = None
    metadata_time: str | None = None
    exercise_info: dict[str, float | str] = {}

    for element in root.iter():
        name = _local_name(element.tag)
        if name == "metadate" and element.text:
            metadata_time = element.text.strip()
        elif name == "metadata":
            for child in element:
                if _local_name(child.tag) == "time" and child.text:
                    metadata_time = child.text.strip()
                    break
        if name == "trk" and track_name is None:
            for child in element:
                if _local_name(child.tag) == "name" and child.text:
                    track_name = child.text.strip()
                    break
        if name == "exerciseinfo":
            for child in element:
                key = _local_name(child.tag)
                text = (child.text or "").strip()
                try:
                    exercise_info[key] = float(text)
                except ValueError:
                    exercise_info[key] = text

    for segment_element in (e for e in root.iter() if _local_name(e.tag) == "trkseg"):
        segment: list[TrackPoint] = []
        for element in segment_element:
            if _local_name(element.tag) != "trkpt":
                continue
            try:
                latitude = float(element.attrib["lat"])
                longitude = float(element.attrib["lon"])
            except (KeyError, ValueError) as exc:
                raise ValueError("A GPX track point has an invalid latitude or longitude") from exc
            if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
                raise ValueError(f"Out-of-range coordinate: ({latitude}, {longitude})")
            elevation = 0.0
            timestamp: datetime | None = None
            for child in element:
                child_name = _local_name(child.tag)
                if child_name == "ele" and child.text:
                    try:
                        elevation = float(child.text)
                    except ValueError as exc:
                        raise ValueError(f"Invalid elevation at ({latitude}, {longitude})") from exc
                elif child_name == "time":
                    timestamp = _parse_time(child.text)
            segment.append(TrackPoint(latitude, longitude, elevation, timestamp))
        if segment:
            segments.append(segment)

    if not segments:
        raise ValueError("The GPX file contains no non-empty track segments")
    return GPXData(
        segments=segments,
        creator=root.attrib.get("creator"),
        version=root.attrib.get("version"),
        track_name=track_name,
        metadata_time=metadata_time,
        exercise_info=exercise_info,
    )


def parse_gpx(path: str | Path) -> GPXData:
    """Open a GPX pathname and delegate parsing to :func:`parse_gpx_stream`."""
    source = Path(path)
    try:
        with source.open("rb") as handle:
            return parse_gpx_stream(handle)
    except OSError as exc:
        raise ValueError(f"Cannot read GPX file {source}: {exc}") from exc


def geodetic_to_ecef(point: TrackPoint) -> tuple[float, float, float]:
    """Convert a WGS-84 geodetic point to ECEF XYZ, in metres."""
    phi = math.radians(point.latitude_deg)
    lam = math.radians(point.longitude_deg)
    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)
    prime_vertical_radius = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_phi * sin_phi)
    x = (prime_vertical_radius + point.elevation_m) * cos_phi * math.cos(lam)
    y = (prime_vertical_radius + point.elevation_m) * cos_phi * math.sin(lam)
    z = ((1.0 - WGS84_E2) * prime_vertical_radius + point.elevation_m) * sin_phi
    return x, y, z


def euclidean_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((right - left) ** 2 for left, right in zip(a, b)))


def convert_segments_to_ecef(
    segments: Sequence[Sequence[TrackPoint]],
) -> list[list[tuple[float, float, float]]]:
    return [[geodetic_to_ecef(point) for point in segment] for segment in segments]


def consecutive_distances(
    xyz_segments: Sequence[Sequence[Sequence[float]]],
) -> list[float]:
    return [
        euclidean_distance(segment[index - 1], segment[index])
        for segment in xyz_segments
        for index in range(1, len(segment))
    ]


def calculate_corrected_distance(raw_3d_ecef_polyline_length_m: float) -> float:
    """Return the corrected route distance."""
    if not math.isfinite(raw_3d_ecef_polyline_length_m) or raw_3d_ecef_polyline_length_m < 0.0:
        raise ValueError("Raw 3D ECEF polyline length must be a finite non-negative value")
    return raw_3d_ecef_polyline_length_m


def measure_at_scale(
    xyz_segments: Sequence[Sequence[Sequence[float]]], threshold_m: float,
    pass_number: int = 1,
) -> ScaleMeasurement:
    """Run the distance-threshold skipping subroutine from the LabVIEW text.

    Starting at each segment's first point, scan forward and retain the first
    point whose straight-line distance from the last retained point is at least
    ``threshold_m``. A final sub-threshold remainder is not stored, so every
    measured link is at least the critical distance. Separate GPX segments are
    never joined.
    """
    if not math.isfinite(threshold_m) or threshold_m <= 0.0:
        raise ValueError("Scale threshold must be a positive finite number")

    links: list[float] = []
    retained_points = 0
    for segment in xyz_segments:
        if not segment:
            continue
        anchor_index = 0
        accepted_in_segment = 0
        for index in range(1, len(segment)):
            distance = euclidean_distance(segment[anchor_index], segment[index])
            if distance >= threshold_m:
                links.append(distance)
                accepted_in_segment += 1
                anchor_index = index
        if accepted_in_segment:
            retained_points += accepted_in_segment + 1

    total = sum(links)
    average = statistics.fmean(links) if links else 0.0
    return ScaleMeasurement(
        pass_number=pass_number,
        kind="skipped",
        threshold_m=threshold_m,
        scale_m=average,
        length_m=total,
        retained_points=retained_points,
        measured_links=len(links),
        mean_link_m=average,
        standard_deviation_m=statistics.pstdev(links) if len(links) > 1 else 0.0,
        min_link_m=min(links, default=0.0),
        max_link_m=max(links, default=0.0),
    )


def richardson_measurements(
    xyz_segments: Sequence[Sequence[Sequence[float]]],
    multiplier: float,
    maximum_measurements: int,
    maximum_threshold_m: float | None = None,
    first_threshold_m: float | None = None,
    explicit_thresholds_m: Sequence[float] | None = None,
) -> list[ScaleMeasurement]:
    """Create the raw pass followed by recursive LabVIEW-style skip passes.

    The unskipped pass uses its mean consecutive distance as scale ``s``. For
    every later pass, the default critical distance is
    ``R = multiplier * previous_average``. After skipping, the actual average
    accepted distance becomes both the reported scale and the value used to
    calculate the next threshold.
    """
    if multiplier <= 1.0:
        raise ValueError("The average-distance multiplier must be greater than 1")
    if maximum_measurements < 2:
        raise ValueError("At least two measurements (raw plus skipped) are required")

    raw_links = consecutive_distances(xyz_segments)
    if not raw_links:
        raise ValueError("The GPX track must contain consecutive points")
    raw_average = statistics.fmean(raw_links)
    measurements = [
        ScaleMeasurement(
            pass_number=0,
            kind="raw",
            threshold_m=None,
            scale_m=raw_average,
            length_m=sum(raw_links),
            retained_points=sum(len(segment) for segment in xyz_segments),
            measured_links=len(raw_links),
            mean_link_m=raw_average,
            standard_deviation_m=statistics.pstdev(raw_links) if len(raw_links) > 1 else 0.0,
            min_link_m=min(raw_links),
            max_link_m=max(raw_links),
        )
    ]

    if explicit_thresholds_m is not None:
        for pass_number, threshold in enumerate(explicit_thresholds_m[: maximum_measurements - 1], start=1):
            result = measure_at_scale(xyz_segments, threshold, pass_number)
            if result.measured_links == 0:
                break
            measurements.append(result)
        return measurements

    previous_average = raw_average
    for pass_number in range(1, maximum_measurements):
        threshold = first_threshold_m if pass_number == 1 and first_threshold_m is not None else multiplier * previous_average
        if maximum_threshold_m is not None and threshold > maximum_threshold_m:
            break
        result = measure_at_scale(xyz_segments, threshold, pass_number)
        if result.measured_links == 0:
            break
        measurements.append(result)
        previous_average = result.mean_link_m
    return measurements


def fit_log_log(measurements: Sequence[ScaleMeasurement]) -> LinearFit:
    valid = [m for m in measurements if m.used_in_fit and m.scale_m > 0 and m.length_m > 0]
    if len(valid) < 2:
        raise ValueError("At least two valid scale measurements are required for a fit")
    x = [math.log(m.scale_m) for m in valid]
    y = [math.log(m.length_m) for m in valid]
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    ss_x = sum((value - x_mean) ** 2 for value in x)
    if ss_x == 0.0:
        raise ValueError("Scale values must not all be equal")
    slope = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y)) / ss_x
    intercept = y_mean - slope * x_mean
    residual = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, y))
    total = sum((yi - y_mean) ** 2 for yi in y)
    r_squared = 1.0 - residual / total if total > 0.0 else 1.0
    return LinearFit(slope, intercept, r_squared, 1.0 - slope, len(valid))


def _bounds(points: Sequence[TrackPoint]) -> dict[str, float]:
    return {
        "min_latitude_deg": min(p.latitude_deg for p in points),
        "max_latitude_deg": max(p.latitude_deg for p in points),
        "min_longitude_deg": min(p.longitude_deg for p in points),
        "max_longitude_deg": max(p.longitude_deg for p in points),
        "min_elevation_m": min(p.elevation_m for p in points),
        "max_elevation_m": max(p.elevation_m for p in points),
    }


def _timestamp_summary(points: Sequence[TrackPoint]) -> dict[str, object]:
    times = [p.time for p in points if p.time is not None]
    if not times:
        return {"points_with_timestamps": 0}
    intervals = [
        (later - earlier).total_seconds()
        for earlier, later in zip(times, times[1:])
        if later >= earlier
    ]
    return {
        "points_with_timestamps": len(times),
        "start_utc": times[0].isoformat(),
        "end_utc": times[-1].isoformat(),
        "elapsed_s": (times[-1] - times[0]).total_seconds(),
        "median_interval_s": statistics.median(intervals) if intervals else None,
        "max_interval_s": max(intervals, default=None),
    }


def _write_xyz_csv(
    path: Path,
    segments: Sequence[Sequence[TrackPoint]],
    xyz_segments: Sequence[Sequence[Sequence[float]]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["segment", "point", "latitude_deg", "longitude_deg", "elevation_m", "time", "x_m", "y_m", "z_m"])
        for segment_index, (segment, xyz_segment) in enumerate(zip(segments, xyz_segments), start=1):
            for point_index, (point, xyz) in enumerate(zip(segment, xyz_segment), start=1):
                writer.writerow([
                    segment_index,
                    point_index,
                    point.latitude_deg,
                    point.longitude_deg,
                    point.elevation_m,
                    point.time.isoformat() if point.time else "",
                    *xyz,
                ])


def _write_scales_csv(path: Path, measurements: Sequence[ScaleMeasurement]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(measurements[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(measurement) for measurement in measurements)


def _write_report(path: Path, summary: dict[str, object]) -> None:
    gpx = summary["gpx"]
    raw = summary["raw_track"]
    fit = summary["linear_fit"]
    measurements = [item for item in summary["measurements"] if item["used_in_fit"]]
    comparison = raw["reported_distance_comparison"]
    scale_settings = summary["scale_settings"]
    stop_detail = scale_settings["termination_reason"]
    if scale_settings["next_unprocessed_threshold_m"] is not None:
        stop_detail += f"; next R would be {scale_settings['next_unprocessed_threshold_m']:.3f} m"
    lines = [
        "# GPX fractal-route analysis",
        "",
        f"- Input track: `{gpx['track_name']}`",
        f"- Source: {gpx['creator']}; GPX {gpx['version']}",
        f"- Samples: {gpx['point_count']:,} points in {gpx['segment_count']} segment(s)",
        f"- Recorded interval: {gpx['timestamps']['start_utc']} to {gpx['timestamps']['end_utc']} ({gpx['timestamps']['elapsed_s']:.0f} s elapsed)",
        f"- Typical sampling interval: {gpx['timestamps']['median_interval_s']:.1f} s; largest gap: {gpx['timestamps']['max_interval_s']:.1f} s",
        f"- Coordinate bounds: latitude {gpx['bounds']['min_latitude_deg']:.6f}° to {gpx['bounds']['max_latitude_deg']:.6f}°, longitude {gpx['bounds']['min_longitude_deg']:.6f}° to {gpx['bounds']['max_longitude_deg']:.6f}°",
        f"- Elevation range: {gpx['bounds']['min_elevation_m']:.3f} to {gpx['bounds']['max_elevation_m']:.3f} m",
        f"- Corrected distance: **{summary['corrected_distance_m']:.3f} m** ({summary['corrected_distance_method']})",
        f"- Raw 3D ECEF polyline length: {raw['ecef_polyline_length_m']:.3f} m",
        f"- Mean / median raw point spacing: {raw['mean_link_m']:.3f} / {raw['median_link_m']:.3f} m",
        f"- Straight-line start-to-end distance: {raw['start_to_end_distance_m']:.3f} m",
    ]
    if comparison:
        lines.append(
            f"- Samsung-reported distance: {comparison['reported_distance_m']:.3f} m; raw ECEF result is {comparison['percent_difference']:+.3f}% different"
        )
    lines.extend([
        "",
        "## Fractal fit",
        "",
        f"The fit used {fit['point_count']} mean-chord scales from {measurements[0]['scale_m']:.3f} to {measurements[-1]['scale_m']:.3f} m:",
        "",
        f"`{fit['equation']}`",
        "",
        f"- Slope: {fit['slope']:.9f}",
        f"- Intercept ln(a): {fit['intercept']:.9f}",
        f"- Fractal dimension `D = 1 - slope`: **{fit['fractal_dimension']:.6f}**",
        f"- R²: {fit['r_squared']:.6f}",
        f"- Scale-generation stop: {stop_detail}",
        "",
        "The dimension is an estimate for this GPS trace over the stated scale range. Fine-scale GPS noise, sampling, and the fitting range affect it. Following the supplied LabVIEW algorithm, a final chord shorter than the critical distance is discarded rather than appended.",
        "",
        "See `analysis.svg` for the route and log-log fit, `length_vs_scale.csv` for every scale measurement, and `analysis_summary.json` for complete metadata and settings.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _svg_polyline(points: Iterable[tuple[float, float]], color: str, width: float = 2.0) -> str:
    coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>'


def _log_axis_ticks(minimum: float, maximum: float) -> list[float]:
    """Return readable tick values for an axis positioned logarithmically."""
    if minimum <= 0.0 or maximum <= minimum:
        return []
    log_span = math.log10(maximum) - math.log10(minimum)
    multipliers = range(1, 10) if log_span < 1.0 else (1, 2, 5)
    first_decade = math.floor(math.log10(minimum)) - 1
    last_decade = math.ceil(math.log10(maximum)) + 1
    return [
        multiplier * 10.0**decade
        for decade in range(first_decade, last_decade + 1)
        for multiplier in multipliers
        if minimum <= multiplier * 10.0**decade <= maximum
    ]


def _format_axis_tick(value: float) -> str:
    if value >= 1_000.0:
        return f"{value:,.0f}"
    if value >= 10.0:
        return f"{value:.0f}"
    if value >= 1.0:
        return f"{value:g}"
    return f"{value:.2g}"


def _write_svg(
    path: Path,
    points: Sequence[TrackPoint],
    measurements: Sequence[ScaleMeasurement],
    fit: LinearFit,
    title: str,
) -> None:
    width, height = 1200, 640
    route_box = (70.0, 80.0, 500.0, 400.0)
    fit_box = (690.0, 80.0, 440.0, 400.0)

    mean_lat = math.radians(statistics.fmean(p.latitude_deg for p in points))
    route_x = [p.longitude_deg * math.cos(mean_lat) for p in points]
    route_y = [p.latitude_deg for p in points]
    x_min, x_max = min(route_x), max(route_x)
    y_min, y_max = min(route_y), max(route_y)

    def project(values_x: Sequence[float], values_y: Sequence[float], box: tuple[float, float, float, float]) -> list[tuple[float, float]]:
        bx, by, bw, bh = box
        dx = max(max(values_x) - min(values_x), 1e-15)
        dy = max(max(values_y) - min(values_y), 1e-15)
        return [
            (bx + (x - min(values_x)) / dx * bw, by + bh - (y - min(values_y)) / dy * bh)
            for x, y in zip(values_x, values_y)
        ]

    route_projected = project(route_x, route_y, route_box)
    # Plot the regression population only so an optional user-selected fit
    # cutoff does not compress the useful plot range.
    used = [m for m in measurements if m.used_in_fit]
    log_x = [math.log(m.scale_m) for m in used]
    log_y = [math.log(m.length_m) for m in used]
    all_x_min, all_x_max = min(log_x), max(log_x)
    fit_y_at_edges = [fit.intercept + fit.slope * x for x in (all_x_min, all_x_max)]
    combined_y = log_y + fit_y_at_edges
    bx, by, bw, bh = fit_box
    dy = max(max(combined_y) - min(combined_y), 1e-15)
    fit_line = [
        (bx, by + bh - (fit_y_at_edges[0] - min(combined_y)) / dy * bh),
        (bx + bw, by + bh - (fit_y_at_edges[1] - min(combined_y)) / dy * bh),
    ]
    # Reproject scatter using the same y limits as the fit line.
    dx = max(all_x_max - all_x_min, 1e-15)
    plot_points = [
        (bx + (x - all_x_min) / dx * bw, by + bh - (y - min(combined_y)) / dy * bh)
        for x, y in zip(log_x, log_y)
    ]
    y_log_min, y_log_max = min(combined_y), max(combined_y)

    def map_scale(value: float) -> float:
        return bx + (math.log(value) - all_x_min) / dx * bw

    def map_length(value: float) -> float:
        return by + bh - (math.log(value) - y_log_min) / dy * bh

    x_ticks = _log_axis_ticks(math.exp(all_x_min), math.exp(all_x_max))
    y_ticks = _log_axis_ticks(math.exp(y_log_min), math.exp(y_log_max))
    grid: list[str] = []
    for tick in x_ticks:
        x = map_scale(tick)
        grid.append(f'<line class="grid" x1="{x:.2f}" y1="{by}" x2="{x:.2f}" y2="{by + bh}"/>')
        grid.append(f'<line class="tick" x1="{x:.2f}" y1="{by + bh}" x2="{x:.2f}" y2="{by + bh + 6}"/>')
        grid.append(f'<text class="tick-label" x="{x:.2f}" y="{by + bh + 22}" text-anchor="middle">{_format_axis_tick(tick)}</text>')
    for tick in y_ticks:
        y = map_length(tick)
        grid.append(f'<line class="grid" x1="{bx}" y1="{y:.2f}" x2="{bx + bw}" y2="{y:.2f}"/>')
        grid.append(f'<line class="tick" x1="{bx - 6}" y1="{y:.2f}" x2="{bx}" y2="{y:.2f}"/>')
        grid.append(f'<text class="tick-label" x="{bx - 11}" y="{y + 4:.2f}" text-anchor="end">{_format_axis_tick(tick)}</text>')

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfcfe"/>',
        '<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#162033}.title{font-size:21px;font-weight:600}.label{font-size:14px}.axis-label{font-size:16px;font-weight:600}.tick-label{font-size:12px;fill:#3f4b5e}.small{font-size:12px;fill:#556070}.grid{stroke:#e3e8ef;stroke-width:1}.tick{stroke:#586477;stroke-width:1.2}</style>',
        f'<text class="title" x="50" y="38">{escape(title)}</text>',
        '<text class="label" x="70" y="65">Track geometry (longitude corrected by cos(latitude))</text>',
        '<text class="label" x="690" y="65">Richardson log-log fit (both axes logarithmic)</text>',
        f'<rect x="{route_box[0]}" y="{route_box[1]}" width="{route_box[2]}" height="{route_box[3]}" fill="white" stroke="#ccd4df"/>',
        f'<rect x="{fit_box[0]}" y="{fit_box[1]}" width="{fit_box[2]}" height="{fit_box[3]}" fill="white" stroke="#ccd4df"/>',
        *grid,
        _svg_polyline(route_projected, "#1464f4", 1.5),
        _svg_polyline(fit_line, "#dc3d43", 2.0),
    ]
    for x, y in plot_points:
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.2" fill="#1464f4"/>')
    svg.extend([
        f'<text class="small" x="70" y="515">Latitude {y_min:.6f}° to {y_max:.6f}°; longitude {min(p.longitude_deg for p in points):.6f}° to {max(p.longitude_deg for p in points):.6f}°</text>',
        f'<text class="axis-label" x="{bx + bw / 2:.2f}" y="{by + bh + 52:.2f}" text-anchor="middle">Scale, s (m)</text>',
        f'<text class="axis-label" x="{bx - 66:.2f}" y="{by + bh / 2:.2f}" text-anchor="middle" transform="rotate(-90 {bx - 66:.2f} {by + bh / 2:.2f})">Distance, L (m)</text>',
        f'<text class="small" x="690" y="565">ln(L) = {fit.intercept:.6f} {fit.slope:+.6f} ln(s); D = {fit.fractal_dimension:.6f}; R² = {fit.r_squared:.6f}; fit points = {len(used)}</text>',
        '<text class="small" x="690" y="588">Blue: scale measurements included in fit · red: fitted line; tick labels show metres</text>',
        '</svg>',
    ])
    path.write_text("\n".join(svg), encoding="utf-8")


def analyze_gpx_data(
    data: GPXData,
    config: AnalysisConfig,
    source_name: str | None = None,
) -> AnalysisResult:
    """Analyze parsed GPX data without CLI behavior or filesystem side effects."""
    points = [point for segment in data.segments for point in segment]
    xyz_segments = convert_segments_to_ecef(data.segments)
    raw_links = consecutive_distances(xyz_segments)
    if not raw_links or sum(raw_links) <= 0.0:
        raise ValueError("The GPX track must contain at least two distinct points")

    raw_length = sum(raw_links)
    corrected_distance = calculate_corrected_distance(raw_length)
    scales = config.explicit_scales_m
    if scales is not None and (
        not scales or any(not math.isfinite(value) or value <= 0 for value in scales)
    ):
        raise ValueError("Explicit scales must contain positive finite critical distances")

    measured = richardson_measurements(
        xyz_segments,
        multiplier=config.scale_factor,
        maximum_measurements=config.num_scales,
        maximum_threshold_m=config.max_scale_m,
        first_threshold_m=config.min_scale_m,
        explicit_thresholds_m=scales,
    )
    measurements = [
        ScaleMeasurement(**{**asdict(item), "used_in_fit": item.retained_points >= config.min_retained_points and item.length_m > 0})
        for item in measured
    ]
    fit = fit_log_log(measurements)

    if scales is not None:
        expected_measurements = 1 + min(len(scales), config.num_scales - 1)
        next_threshold = None
        termination_reason = (
            "explicit_thresholds_completed_or_maximum_count_reached"
            if len(measurements) == expected_measurements
            else "no_chord_reached_next_explicit_threshold"
        )
    else:
        next_threshold = (
            config.min_scale_m
            if len(measurements) == 1 and config.min_scale_m is not None
            else config.scale_factor * measurements[-1].mean_link_m
        )
        if len(measurements) >= config.num_scales:
            termination_reason = "maximum_measurement_count_reached"
        elif config.max_scale_m is not None and next_threshold > config.max_scale_m:
            termination_reason = "maximum_threshold_reached"
        else:
            termination_reason = "no_chord_reached_next_threshold"

    reported_distance = data.exercise_info.get("distance")
    comparison = None
    if isinstance(reported_distance, (int, float)) and reported_distance:
        comparison = {
            "reported_distance_m": reported_distance,
            "ecef_minus_reported_m": raw_length - reported_distance,
            "percent_difference": 100.0 * (raw_length - reported_distance) / reported_distance,
        }
    summary: dict[str, object] = {
        "source_name": ntpath.basename(source_name) if source_name else None,
        "corrected_distance_m": corrected_distance,
        "corrected_distance_method": "corrected route distance",
        "method": {
            "coordinate_system": "WGS-84 geodetic to ECEF XYZ",
            "distance": "3D Euclidean chord distance in ECEF metres",
            "skipping": "retain first point at least R metres from last retained point; discard a final sub-R remainder",
            "fit_equation": "ln(L) = ln(a) + (1-D) ln(s)",
            "scale_definition": "s is the actual mean accepted chord length (Aver); recursively set next R = multiplier * previous Aver",
        },
        "gpx": {
            "version": data.version,
            "creator": data.creator,
            "track_name": data.track_name,
            "metadata_time": data.metadata_time,
            "segment_count": len(data.segments),
            "point_count": len(points),
            "points_per_segment": [len(segment) for segment in data.segments],
            "bounds": _bounds(points),
            "timestamps": _timestamp_summary(points),
            "exercise_info": data.exercise_info,
        },
        "raw_track": {
            "ecef_polyline_length_m": raw_length,
            "start_to_end_distance_m": euclidean_distance(xyz_segments[0][0], xyz_segments[-1][-1]),
            "link_count": len(raw_links),
            "mean_link_m": statistics.fmean(raw_links),
            "median_link_m": statistics.median(raw_links),
            "min_link_m": min(raw_links),
            "max_link_m": max(raw_links),
            "reported_distance_comparison": comparison,
        },
        "scale_settings": {
            "raw_mean_scale_m": statistics.fmean(raw_links),
            "average_distance_multiplier": config.scale_factor if scales is None else None,
            "maximum_measurement_count_including_raw": config.num_scales,
            "first_threshold_override_m": config.min_scale_m,
            "explicit_thresholds_m": scales,
            "minimum_retained_points_for_fit": config.min_retained_points,
            "termination_reason": termination_reason,
            "next_unprocessed_threshold_m": next_threshold,
        },
        "measurements": [asdict(item) for item in measurements],
        "linear_fit": {
            **asdict(fit),
            "a_m": math.exp(fit.intercept),
            "equation": f"ln(L) = {fit.intercept:.9f} + ({fit.slope:.9f}) ln(s)",
        },
        "cautions": [
            "The estimate describes this sampled GPS trace over the fitted mean-chord scale range, not an intrinsic dimension valid at every scale.",
            "GPX <ele> is commonly orthometric elevation, while WGS-84 ECEF formally expects ellipsoidal height; for a local route, a nearly constant geoid offset has negligible effect on successive distances.",
            "GPS noise can inflate fine-scale length; inspect the log-log plot and R-squared before interpreting D.",
            "Per the supplied algorithm, the final endpoint contributes only when its distance from the current anchor reaches R.",
        ],
    }
    return AnalysisResult(data, xyz_segments, measurements, fit, summary)


def write_analysis_outputs(result: AnalysisResult, output_dir: str | Path) -> Path:
    """Write all CLI artifacts from an existing result without reanalysis."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    points = [point for segment in result.data.segments for point in segment]
    _write_xyz_csv(destination / "route_xyz.csv", result.data.segments, result.xyz_segments)
    _write_scales_csv(destination / "length_vs_scale.csv", result.measurements)
    (destination / "analysis_summary.json").write_text(
        json.dumps(result.summary, indent=2), encoding="utf-8"
    )
    _write_report(destination / "REPORT.md", result.summary)
    title = result.data.track_name or result.summary.get("source_name") or "GPX track"
    _write_svg(destination / "analysis.svg", points, result.measurements, result.fit, str(title))
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input .gpx file")
    parser.add_argument("--output-dir", type=Path, default=Path("results"), help="Output directory (default: results)")
    parser.add_argument("--min-scale", type=float, default=None, help="Override the first critical distance R in metres (default: multiplier * raw mean)")
    parser.add_argument("--max-scale", type=float, default=None, help="Optional maximum critical distance R in metres")
    parser.add_argument("--scale-factor", type=float, default=1.5, help="Multiplier applied to the previous accepted-distance average (default: 1.5)")
    parser.add_argument("--num-scales", type=int, default=14, help="Maximum measurements including the raw pass (default: 14)")
    parser.add_argument("--scales", help="Explicit comma-separated critical distances R; includes the raw pass automatically")
    parser.add_argument("--min-retained-points", type=int, default=2, help="Optional fit cutoff (default: 2, so every non-empty pass is fitted)")
    return parser


def _parse_cli_scales(value: str | None) -> tuple[float, ...] | None:
    """Translate the CLI's comma-separated representation into numeric scales."""
    if not value:
        return None
    try:
        scales = tuple(sorted({float(item) for item in value.split(",")}))
    except ValueError as exc:
        raise ValueError("--scales must be a comma-separated list of numbers in metres") from exc
    if not scales or any(not math.isfinite(scale) or scale <= 0 for scale in scales):
        raise ValueError("--scales must contain positive finite critical distances")
    return scales


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = AnalysisConfig(
            min_scale_m=args.min_scale,
            max_scale_m=args.max_scale,
            scale_factor=args.scale_factor,
            num_scales=args.num_scales,
            explicit_scales_m=_parse_cli_scales(args.scales),
            min_retained_points=args.min_retained_points,
        )
        data = parse_gpx(args.input)
        result = analyze_gpx_data(data, config, source_name=args.input.name)
        output_dir = write_analysis_outputs(result, args.output_dir)
    except ValueError as exc:
        parser.error(str(exc))
    summary = result.summary
    fit = summary["linear_fit"]
    gpx = summary["gpx"]
    print(f"Points: {gpx['point_count']} in {gpx['segment_count']} segment(s)")
    print(f"Corrected distance: {summary['corrected_distance_m']:.3f} m")
    print(f"Corrected-distance method: {summary['corrected_distance_method']}")
    print(f"Fit: {fit['equation']}")
    print(f"Fractal dimension D: {fit['fractal_dimension']:.6f}")
    print(f"R-squared: {fit['r_squared']:.6f} ({fit['point_count']} scales)")
    print(f"Outputs: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
