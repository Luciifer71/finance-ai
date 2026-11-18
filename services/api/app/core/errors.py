"""Errors as RFC 9457 "problem details" (``application/problem+json``).

Every error the API returns has the same shape::

    {"type": "urn:finance-ai:problem:import.file_too_large",
     "title": "File too large", "status": 413,
     "detail": "The file is larger than 5 MB.",
     "instance": "urn:finance-ai:request:<request id>",
     "code": "import.file_too_large"}

``code`` is stable: the mobile app branches on it, never on ``detail``.
Responses never contain stack traces, SQL or another user's data.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import current_request_id

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

_STATUS_CODES = {
    400: ("request.bad_request", "Bad request"),
    401: ("auth.unauthorized", "Not authenticated"),
    403: ("auth.forbidden", "Forbidden"),
    404: ("resource.not_found", "Not found"),
    405: ("request.method_not_allowed", "Method not allowed"),
    409: ("resource.conflict", "Conflict"),
    413: ("request.too_large", "Request too large"),
    415: ("request.unsupported_media_type", "Unsupported media type"),
    422: ("request.validation_failed", "Validation failed"),
    429: ("rate_limit.exceeded", "Too many requests"),
    500: ("server.error", "Internal server error"),
    503: ("server.unavailable", "Service unavailable"),
}


class ProblemError(Exception):
    """Raise from services or routers to return a problem response."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers
        self.extra = extra or {}


class NotFoundError(ProblemError):
    """The resource does not exist *for this user*. Used for other users' rows too."""

    def __init__(self, resource: str = "resource") -> None:
        super().__init__(404, f"{resource}.not_found", "Not found", f"No such {resource}.")


def problem_response(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    *,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:finance-ai:problem:{code}",
        "title": title,
        "status": status,
        "detail": detail or title,
        "instance": f"urn:finance-ai:request:{current_request_id() or 'unknown'}",
        "code": code,
    }
    body.update(extra or {})
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


def _field_name(location: tuple[Any, ...] | list[Any]) -> str:
    # ("body", "amount") -> "amount"; ("query", "limit") -> "limit"
    parts = [str(part) for part in location]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    return ".".join(parts) or "request"


async def _problem_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ProblemError):  # pragma: no cover - registered for this type only
        raise exc
    return problem_response(
        exc.status, exc.code, exc.title, exc.detail, headers=exc.headers, extra=exc.extra
    )


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise exc
    # Only the field path and pydantic's message; never the rejected input value.
    errors = [
        {"field": _field_name(err.get("loc", ())), "message": str(err.get("msg", "invalid"))}
        for err in exc.errors()
    ]
    return problem_response(
        422,
        "request.validation_failed",
        "Validation failed",
        "One or more fields are invalid.",
        extra={"errors": errors},
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise exc
    code, title = _STATUS_CODES.get(exc.status_code, ("request.error", "Request error"))
    detail = exc.detail if isinstance(exc.detail, str) else None
    headers = dict(exc.headers) if exc.headers else None
    return problem_response(exc.status_code, code, title, detail, headers=headers)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the type only; the message could contain user data or SQL.
    logger.error("unhandled_error", extra={"error_type": type(exc).__name__})
    return problem_response(500, "server.error", "Internal server error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
