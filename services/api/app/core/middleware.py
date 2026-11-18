"""Request middleware: request id, access log, security headers, body limit.

Written as plain ASGI (not ``BaseHTTPMiddleware``) so the request id context
variable is visible to every log line made while handling the request.
"""

import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import problem_response
from app.core.logging import current_user_hash, set_request_context

access_logger = logging.getLogger("app.access")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_API_PREFIX = "/api/v1"
_API_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
]


def _path_template(scope: Scope) -> str:
    """The route pattern (``/api/v1/accounts/{account_id}``), never the raw path with ids.

    Newer FastAPI versions report an included route's own path without the router
    prefixes ("/accounts"). Path parameters here are always one segment, so the
    prefix is the raw path's leading segments that the template does not cover.
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    if not isinstance(template, str):
        return "<unmatched>"
    raw_segments = scope["path"].rstrip("/").split("/")
    template_segments = template.rstrip("/").split("/")
    extra = len(raw_segments) - len(template_segments)
    if extra <= 0:
        return template
    return "/".join(raw_segments[: extra + 1]) + "/" + "/".join(template_segments[1:])


class RequestContextMiddleware:
    """Assign a request id, add headers, and write one access log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, b"x-request-id")
        request_id = (
            incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        )
        set_request_context(request_id)
        is_api = scope["path"].startswith(_API_PREFIX)
        started = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                if is_api:
                    headers.extend(_API_HEADERS)
                else:
                    headers.append((b"x-content-type-options", b"nosniff"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            access_logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": _path_template(scope),
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "user": current_user_hash(),
                },
            )


class BodySizeLimitMiddleware:
    """Reject request bodies over a limit before they are read into memory.

    Uploads get their own (larger) limit, enforced by the import endpoint while
    streaming the file; here they are only capped at that larger size.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int, max_upload_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_upload_bytes = max_upload_bytes

    def _limit_for(self, scope: Scope) -> int:
        content_type = _header(scope, b"content-type") or ""
        if content_type.startswith("multipart/form-data"):
            # File size limit plus room for the multipart envelope and form fields.
            return self.max_upload_bytes + 64 * 1024
        return self.max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _send_too_large(scope, receive, send)
            return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message: Message) -> None:
            # FastAPI turns errors while reading the body into its own 400
            # response; once we know the body was too large, replace it.
            nonlocal response_started
            if too_large:
                if message["type"] == "http.response.start" and not response_started:
                    response_started = True
                    await _send_too_large(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if not response_started:
                await _send_too_large(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = problem_response(
        413, "request.too_large", "Request too large", "The request body is too large."
    )
    await response(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    headers: Any = scope.get("headers", [])
    for key, value in headers:
        if key == name:
            decoded: str = value.decode("latin-1")
            return decoded
    return None
