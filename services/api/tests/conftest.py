"""Shared test fixtures.

Database tests run against the real PostgreSQL test database, inside a
transaction that is rolled back at the end of each test. Service code may call
``session.commit()``: with ``join_transaction_mode="create_savepoint"`` that only
releases a savepoint, so nothing ever reaches the database for good.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.security import StaticKeyProvider, TokenVerifier, key_id_for, mint_token
from app.database import get_db
from app.main import create_app

# A fixed "today" for API tests: Wednesday 18 Nov 2026, noon in India.
TODAY = date(2026, 11, 18)
TEST_ISSUER = "https://auth.invalid/auth/v1"
TEST_AUDIENCE = "authenticated"


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
        auth_issuer=TEST_ISSUER,
        rate_limit_enabled=False,
    )


# --- authentication and API client --------------------------------------------------


@pytest.fixture(scope="session")
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def token_verifier(signing_key: ec.EllipticCurvePrivateKey) -> TokenVerifier:
    public_key = signing_key.public_key()
    return TokenVerifier(
        StaticKeyProvider({key_id_for(public_key): (public_key, "ES256")}),
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        algorithms=["ES256", "RS256"],
    )


TokenFactory = Callable[..., str]


@pytest.fixture
def make_token(signing_key: ec.EllipticCurvePrivateKey, clock: FixedClock) -> TokenFactory:
    def factory(
        subject: str | None = None,
        email: str | None = None,
        *,
        lifetime: timedelta = timedelta(hours=1),
        **overrides: Any,
    ) -> str:
        subject = subject or str(uuid.uuid4())
        return mint_token(
            overrides.pop("key", signing_key),
            subject=subject,
            email=email or f"{subject[:8]}@example.test",
            issuer=overrides.pop("issuer", TEST_ISSUER),
            audience=overrides.pop("audience", TEST_AUDIENCE),
            now=overrides.pop("now", clock.now()),
            lifetime=lifetime,
            extra_claims=overrides.pop("extra_claims", None),
            headers=overrides.pop("headers", None),
        )

    return factory


@pytest.fixture
def app(
    settings: Settings, clock: FixedClock, token_verifier: TokenVerifier, db_session: Session
) -> FastAPI:
    application = create_app(settings, clock=clock, token_verifier=token_verifier)

    def override_get_db() -> Iterator[Session]:
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@dataclass
class ApiUser:
    id: uuid.UUID
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _sign_in(client: TestClient, make_token: TokenFactory, email: str) -> ApiUser:
    token = make_token(str(uuid.uuid4()), email)
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return ApiUser(id=uuid.UUID(response.json()["id"]), email=email, token=token)


@pytest.fixture
def user_a(client: TestClient, make_token: TokenFactory) -> ApiUser:
    return _sign_in(client, make_token, "user.a@example.test")


@pytest.fixture
def user_b(client: TestClient, make_token: TokenFactory) -> ApiUser:
    return _sign_in(client, make_token, "user.b@example.test")
