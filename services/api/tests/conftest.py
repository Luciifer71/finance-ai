"""Shared test fixtures.

Database tests run against the real PostgreSQL test database, inside a
transaction that is rolled back at the end of each test. Service code may call
``session.commit()``: with ``join_transaction_mode="create_savepoint"`` that only
releases a savepoint, so nothing ever reaches the database for good.
"""

import os
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.config import Settings

# A fixed "today" for API tests: Wednesday 18 Nov 2026, noon in India.
TODAY = date(2026, 11, 18)


def _checked_test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL must be configured explicitly.")

    url = make_url(database_url)
    if (
        url.drivername != "postgresql+psycopg"
        or url.database != "finance_test"
        or url.host not in ("127.0.0.1", "localhost")
        or url.port != 5432
    ):
        pytest.fail("Refusing to run against an unexpected database.")

    if database_url == os.environ.get("DATABASE_URL"):
        pytest.fail("Test database must differ from development database.")
    return database_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _checked_test_database_url()


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose writes are all rolled back after the test."""
    with engine.connect() as connection:
        outer_transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            if outer_transaction.is_active:
                outer_transaction.rollback()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock.at_date(TODAY)


@pytest.fixture
def settings(test_database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=test_database_url,
        auth_mode="jwks",
        auth_jwks_url="https://auth.invalid/jwks.json",
        auth_issuer="https://auth.invalid/auth/v1",
        rate_limit_enabled=False,
    )
