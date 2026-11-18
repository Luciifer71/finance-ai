from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.core.migrations import head_revision
from app.main import app, create_app


def test_health_returns_expected_shape():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "finance-ai-api"}


def test_ready_is_200_when_database_is_up_and_migrated(settings: Settings, engine: Engine):
    with engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert current == head_revision(), "run `alembic upgrade head` on the test database"

    response = TestClient(create_app(settings)).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "migrations": "at_head"}


def test_ready_is_503_when_database_is_unreachable(settings: Settings):
    # Port 1 on localhost: nothing listens there, so the connection is refused at once.
    bad = settings.model_copy(
        update={"database_url": "postgresql+psycopg://finance:finance@127.0.0.1:1/finance"}
    )

    response = TestClient(create_app(bad)).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_ready_is_503_when_database_is_not_configured(settings: Settings):
    response = TestClient(create_app(settings.model_copy(update={"database_url": None}))).get(
        "/health/ready"
    )
    assert response.status_code == 503
    assert response.json()["database"] == "unconfigured"


def test_ready_is_503_when_migrations_are_behind(settings: Settings, engine: Engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("UPDATE alembic_version SET version_num = 'older'"))
        test_app = create_app(settings)
        # Make the app use this uncommitted connection's view of the table.
        test_app.state.engine = _SingleConnectionEngine(connection)
        response = TestClient(test_app).get("/health/ready")
        transaction.rollback()

    assert response.status_code == 503
    assert response.json()["migrations"] == "behind_or_unknown"


class _SingleConnectionEngine:
    """Just enough of an Engine for the readiness check, bound to one connection."""

    def __init__(self, connection):
        self._connection = connection

    def connect(self):
        connection = self._connection

        class _Ctx:
            def __enter__(self):
                return connection

            def __exit__(self, *exc):
                return False

        return _Ctx()
