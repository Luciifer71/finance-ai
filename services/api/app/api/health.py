"""Liveness and readiness checks (public, no authentication)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.migrations import head_revision

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    migrations: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is up. Never touches the database."""
    return HealthResponse(status="ok", service="finance-ai-api")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(request: Request) -> JSONResponse:
    """Readiness: the database answers and its schema is at the latest migration."""
    engine: Engine | None = request.app.state.engine
    database, migrations = "unconfigured", "unknown"
    if engine is not None:
        try:
            with engine.connect() as connection:
                current = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            database = "ok"
            migrations = "at_head" if current == head_revision() else "behind_or_unknown"
        except Exception:  # any failure means "not ready"; details stay out of the response
            database = "unreachable"
    ok = database == "ok" and migrations == "at_head"
    body = ReadinessResponse(
        status="ready" if ok else "not_ready", database=database, migrations=migrations
    )
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
