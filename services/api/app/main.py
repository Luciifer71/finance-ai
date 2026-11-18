"""Application factory.

``create_app(settings)`` builds a fresh app; tests call it with their own
settings. ``app`` at module level is what ``uvicorn app.main:app`` serves,
configured from environment variables.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.core.openapi import install_openapi
from app.core.security import TokenVerifier, build_token_verifier
from app.database import create_db_engine, create_session_factory


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_startup()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Finance AI API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    # Tests inject a verifier holding their own key pair; no network in tests.
    app.state.token_verifier = token_verifier or build_token_verifier(settings)
    app.state.engine = create_db_engine(settings.database_url) if settings.database_url else None
    app.state.session_factory = (
        create_session_factory(app.state.engine) if app.state.engine is not None else None
    )

    install_error_handlers(app)
    install_openapi(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")

    # Starlette runs the last-added middleware first (outermost).
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=settings.max_body_bytes,
        max_upload_bytes=settings.max_upload_bytes,
    )
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Retry-After"],
        )
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
