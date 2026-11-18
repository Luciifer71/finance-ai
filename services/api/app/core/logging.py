"""Structured JSON logs that cannot leak secrets.

Each log line is one JSON object with the request id, so one request can be
followed across lines. A filter scrubs anything that looks like a credential or
an account number before the line is written, as a safety net: code should not
log those things in the first place.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_hash: ContextVar[str | None] = ContextVar("user_hash", default=None)

REDACTED = "[REDACTED]"

# Keys whose values are always secret, wherever they appear.
_SECRET_KEY = re.compile(r"(authorization|token|password|secret|cookie|api[_-]?key)", re.I)
# "Bearer eyJ..." and bare JWTs (three base64url parts).
_BEARER = re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
# Six or more digits in a row: account numbers, card numbers, UPI/UTR references.
_LONG_DIGITS = re.compile(r"\d{6,}")
# key=value / "key": "value" pairs with a secret-looking key.
_SECRET_PAIR = re.compile(
    r"""(?P<key>["']?(?:authorization|token|password|secret|api[_-]?key)["']?\s*[:=]\s*)"""
    r"""(?P<value>"[^"]*"|'[^']*'|[^\s,;&]+)""",
    re.I,
)

# Attributes every LogRecord has; anything else was passed with ``extra=``.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def current_request_id() -> str | None:
    return _request_id.get()


def set_request_context(request_id: str | None, user_hash: str | None = None) -> None:
    _request_id.set(request_id)
    _user_hash.set(user_hash)


def set_user_hash(user_hash: str | None) -> None:
    _user_hash.set(user_hash)


def current_user_hash() -> str | None:
    return _user_hash.get()


def redact_text(text: str) -> str:
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _SECRET_PAIR.sub(lambda m: f"{m.group('key')}{REDACTED}", text)
    return _LONG_DIGITS.sub(REDACTED, text)


def redact_value(key: str, value: Any) -> Any:
    if _SECRET_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(key, v) for v in value]
    return value


class RedactingFilter(logging.Filter):
    """Scrub the message and every ``extra`` field of a record in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact_text(message)
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _STANDARD_ATTRS:
                setattr(record, key, redact_value(key, value))
        return True


class ContextFilter(logging.Filter):
    """Attach the current request id and hashed user id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        record.user_hash = current_user_hash()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            # The exception type only: messages and tracebacks may hold user data.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


class AppLogHandler(logging.StreamHandler[TextIO]):
    """JSON lines to stderr, with context and redaction filters attached."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)
        self.setFormatter(JsonFormatter())
        self.addFilter(ContextFilter())
        self.addFilter(RedactingFilter())


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger. Safe to call more than once."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        if isinstance(handler, AppLogHandler):
            root.removeHandler(handler)
    root.addHandler(AppLogHandler())
