"""Synchronous SQLAlchemy database configuration and request sessions."""

import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _configured_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required for database functionality. "
            "Set it to a postgresql+psycopg:// connection URL."
        )
    return database_url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_configured_database_url(), pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """Provide one SQLAlchemy session per request and always close it."""
    database = get_session_factory()()
    try:
        yield database
    finally:
        database.close()


def initialize_database() -> None:
    """Create current tables and apply the small idempotent schema upgrade."""
    # Import registers the model with Base.metadata without initializing a DB.
    from . import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    ensure_current_route_columns(engine)


def ensure_current_route_columns(engine: Engine) -> None:
    """Idempotently add nullable columns introduced after the first schema."""

    columns = {
        "source_object_key": "VARCHAR(1024)",
        "receive_count": "INTEGER",
        "queue_wait_ms": "FLOAT",
        "analysis_duration_ms": "FLOAT",
        "total_duration_ms": "FLOAT",
    }
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for column_name, column_type in columns.items():
                connection.execute(
                    text(
                        f"ALTER TABLE routes ADD COLUMN IF NOT EXISTS "
                        f"{column_name} {column_type}"
                    )
                )
    else:
        existing = {
            column["name"] for column in inspect(engine).get_columns("routes")
        }
        with engine.begin() as connection:
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE routes ADD COLUMN "
                            f"{column_name} {column_type}"
                        )
                    )
