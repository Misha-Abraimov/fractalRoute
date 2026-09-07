"""SQLAlchemy ORM models."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    track_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    source_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    point_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_3d_ecef_polyline_length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    fractal_dimension: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)
    receive_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_wait_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
