"""PostgreSQL connection and session management."""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


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
