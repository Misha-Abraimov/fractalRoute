"""Stateless FastAPI entry point for the public Vercel deployment."""

from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.formparsers import MultiPartParser

from backend.app.config import get_allowed_origins
from backend.stateless import (
    MAX_GPX_UPLOAD_BYTES,
    MAX_GPX_UPLOAD_MESSAGE,
    analyze_gpx_bytes,
)


# Starlette normally rolls uploads over 1 MiB to a temporary file. Public GPX
# uploads are capped at 4 MiB, so keep the accepted file and one-byte limit
# probe in memory instead.
MultiPartParser.spool_max_size = MAX_GPX_UPLOAD_BYTES + 1


class PublicRouteAnalysisResponse(BaseModel):
    filename: str
    track_name: str | None
    point_count: int
    segment_count: int
    corrected_distance_m: float
    fractal_dimension: float
    r_squared: float
    geometry: dict[str, object]


app = FastAPI(title="Fractal Route Public API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/routes/analyze",
    response_model=PublicRouteAnalysisResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_route(file: UploadFile = File(...)) -> PublicRouteAnalysisResponse:
    contents = await file.read(MAX_GPX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_GPX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=MAX_GPX_UPLOAD_MESSAGE,
        )

    try:
        result = analyze_gpx_bytes(contents, file.filename)
    except OverflowError as exc:
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if detail == "Upload a file with a .gpx extension."
            else 422
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return PublicRouteAnalysisResponse(
        filename=result.filename,
        track_name=result.track_name,
        point_count=result.point_count,
        segment_count=result.segment_count,
        corrected_distance_m=result.corrected_distance_m,
        fractal_dimension=result.fractal_dimension,
        r_squared=result.r_squared,
        geometry=result.geometry,
    )
