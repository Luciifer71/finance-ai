"""Alembic migration environment for Finance AI.

Database connection is configured using the DATABASE_URL
environment variable. Database schema is managed through
SQLAlchemy models and version-controlled Alembic migrations.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.models import Base

# Alembic configuration object.
config = context.config

# Configure logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy metadata used for migration autogeneration.
target_metadata = Base.metadata


def get_database_url() -> str:
    """Retrieve the database URL from environment variables."""
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required to run database migrations."
        )

    return database_url


def run_migrations_offline() -> None:
    """Run migrations without connecting to the database."""

    database_url = get_database_url()

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using an active database connection."""

    database_url = get_database_url()

    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


# Select the appropriate migration mode.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
