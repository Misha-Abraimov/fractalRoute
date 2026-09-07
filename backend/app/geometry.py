"""Portable geographic serialization helpers."""

from fractal_route import GPXData


def gpx_data_to_geojson(data: GPXData) -> dict[str, object]:
    """Convert GPX segments to a 2D GeoJSON MultiLineString."""
    return {
        "type": "MultiLineString",
        "coordinates": [
            [[point.longitude_deg, point.latitude_deg] for point in segment]
            for segment in data.segments
        ],
    }
