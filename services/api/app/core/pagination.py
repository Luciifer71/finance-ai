"""Opaque cursors for keyset pagination on ``(posted_on DESC, id DESC)``.

A cursor is base64url JSON of the last row's sort key. Keyset pagination (not
OFFSET) returns every row exactly once even while new rows arrive, and stays
fast on large tables.
"""

import base64
import binascii
import json
from datetime import date
from uuid import UUID

from app.core.errors import ProblemError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def encode_cursor(posted_on: date, row_id: UUID) -> str:
    payload = json.dumps({"p": posted_on.isoformat(), "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> tuple[date, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return date.fromisoformat(data["p"]), UUID(data["i"])
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise ProblemError(
            422, "pagination.invalid_cursor", "Invalid cursor", "The cursor is not valid."
        ) from exc
