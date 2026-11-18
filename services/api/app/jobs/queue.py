"""Enqueue background jobs into the PostgreSQL ``jobs`` table (the outbox).

Call ``enqueue`` inside the same database transaction as the change that needs
the job: both commit together or neither does. The idempotency key makes a
second enqueue of the same work a no-op.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Job


def enqueue(
    session: Session,
    *,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
    user_id: UUID | None,
    run_after: datetime,
    max_attempts: int = 5,
) -> UUID:
    """``run_after`` comes from the injected clock (usually "now"), never the database's
    own ``now()``, so time-dependent behaviour is the same in tests and production."""
    inserted = session.execute(
        insert(Job)
        .values(
            user_id=user_id,
            kind=kind,
            payload=payload,
            status="queued",
            attempts=0,
            max_attempts=max_attempts,
            run_after=run_after,
            created_at=run_after,
            updated_at=run_after,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        .returning(Job.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted
    return session.execute(
        select(Job.id).where(Job.idempotency_key == idempotency_key)
    ).scalar_one()
