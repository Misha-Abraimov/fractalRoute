"""Public API response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RouteAnalysisResponse(BaseModel):
    filename: str
    track_name: str | None
    point_count: int
    segment_count: int
    raw_3d_ecef_polyline_length_m: float = Field(
        description="Intermediate three-dimensional polyline length in metres."
    )
    corrected_distance_m: float = Field(description="Corrected route distance in metres.")
    fractal_dimension: float
    r_squared: float


RouteStatus = Literal["queued", "processing", "completed", "failed"]


class StoredRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    track_name: str | None
    status: RouteStatus
    point_count: int | None
    segment_count: int | None
    raw_3d_ecef_polyline_length_m: float | None = Field(
        description="Intermediate three-dimensional polyline length in metres."
    )
    corrected_distance_m: float | None = Field(
        description="Corrected route distance in metres when analysis is complete."
    )
    fractal_dimension: float | None
    r_squared: float | None
    geometry: dict[str, object] | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
