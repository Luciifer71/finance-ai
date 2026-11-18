"""Append to ``access_audit``. Never pass tokens, amounts, descriptions or file contents."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AccessAudit


def record(
    session: Session,
    *,
    user_id: UUID | None,
    action: str,
    resource_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Added to the caller's transaction; committed with it."""
    session.add(
        AccessAudit(user_id=user_id, action=action, resource_id=resource_id, details=details or {})
    )
