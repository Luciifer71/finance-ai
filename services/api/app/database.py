"""PostgreSQL connection and session management."""

import os
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ProblemError


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create an engine without immediately opening a connection."""
    url = database_url or os.environ.get("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL environment variable is required")

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Fail fast instead of hanging when the database is down.
        connect_args={"connect_timeout": 5} if url.startswith("postgresql") else {},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


def get_session(
    session_factory: sessionmaker[Session],
) -> Iterator[Session]:
    """Provide a session with cleanup."""
    with session_factory() as session:
        yield session


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Services decide when to commit. Anything not committed when the request
    ends is rolled back when the session closes.
    """
    factory: sessionmaker[Session] | None = request.app.state.session_factory
    if factory is None:
        raise ProblemError(503, "server.database_not_configured", "Database not configured")
    with factory() as session:
        yield session
