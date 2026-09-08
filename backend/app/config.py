"""Environment-backed application configuration shared by API entry points."""

from __future__ import annotations

import os


LOCAL_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def get_allowed_origins() -> list[str]:
    """Return local origins plus any comma-separated production origins."""

    configured = (
        origin.strip().rstrip("/")
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    )
    return list(
        dict.fromkeys(
            [*LOCAL_ALLOWED_ORIGINS, *(origin for origin in configured if origin)]
        )
    )
