import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.database import create_db_engine, create_session_factory


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_db_engine()


def test_session_factory_executes_query():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    factory = create_session_factory(engine)

    try:
        with factory() as session:
            result = session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        engine.dispose()
