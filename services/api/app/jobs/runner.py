"""The background job runner (handoff section 9).

One loop step:
1. Release work that is ready again: ``failed`` jobs whose retry time has come
   go back to ``queued``; ``running`` jobs locked more than 10 minutes ago (the
   worker died) are re-queued, or ``dead`` if they used up their attempts.
2. Claim one ``queued`` job with ``SELECT ... FOR UPDATE SKIP LOCKED``: two
   workers can never claim the same job, and neither waits for the other.
   Claiming counts as an attempt, so a crash mid-job also uses one up.
3. Run its handler in a fresh database transaction. On success the handler's
   changes and the ``succeeded`` status commit together. On an exception the
   handler's changes are rolled back and the job is ``failed`` with a retry time
   (2^attempts seconds, at most 15 minutes, with jitter), or ``dead`` after
   ``max_attempts``.

Handlers must be idempotent: running one twice must change nothing the second time.
"""

import logging
import random
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.models import Job

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)
MAX_BACKOFF_SECONDS = 15 * 60

Handler = Callable[[Session, Job], None]
SessionScope = Callable[[], AbstractContextManager[Session]]


def backoff_seconds(attempts: int, rand: Callable[[], float] = random.random) -> float:
    """2^attempts seconds, capped at 15 minutes, times a random factor in [0.75, 1.0]
    so many failing jobs do not all retry at the same instant."""
    base = min(2**attempts, MAX_BACKOFF_SECONDS)
    return float(base * (0.75 + 0.25 * rand()))


def release_ready(session: Session, now: datetime) -> None:
    session.execute(
        update(Job)
        .where(Job.status == "failed", Job.run_after <= now)
        .values(status="queued", updated_at=now)
    )
    stale = Job.status == "running", Job.locked_at < now - STALE_AFTER
    session.execute(
        update(Job)
        .where(*stale, Job.attempts >= Job.max_attempts)
        .values(
            status="dead", locked_by=None, locked_at=None, updated_at=now, last_error="StaleLock"
        )
    )
    session.execute(
        update(Job)
        .where(*stale)
        .values(status="queued", locked_by=None, locked_at=None, run_after=now, updated_at=now)
    )


def claim_next(session: Session, worker_id: str, now: datetime) -> Job | None:
    job = session.scalars(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.run_after, Job.created_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.locked_at = now
    job.updated_at = now
    session.flush()
    return job


def run_one(
    scope: SessionScope,
    handlers: dict[str, Handler],
    worker_id: str,
    clock: Clock,
    rand: Callable[[], float] = random.random,
) -> UUID | None:
    """Claim and run one job. Returns its id, or None when nothing was ready."""
    with scope() as session:
        release_ready(session, clock.now())
        claimed = claim_next(session, worker_id, clock.now())
        session.commit()
        if claimed is None:
            return None
        job_id, kind = claimed.id, claimed.kind

    try:
        with scope() as session:
            job = session.get(Job, job_id)
            if job is None:  # pragma: no cover - deleted between claim and run
                return job_id
            handler = handlers.get(kind)
            if handler is None:
                raise LookupError(f"no handler for job kind {kind}")
            handler(session, job)
            job.status = "succeeded"
            job.locked_by = None
            job.locked_at = None
            job.last_error = None
            job.updated_at = clock.now()
            session.commit()
            logger.info("job_succeeded", extra={"kind": kind, "job_id": str(job_id)})
    except Exception as exc:  # any handler failure is recorded, never propagated
        _record_failure(scope, job_id, exc, clock, rand)
    return job_id


def _record_failure(
    scope: SessionScope,
    job_id: UUID,
    exc: Exception,
    clock: Clock,
    rand: Callable[[], float],
) -> None:
    now = clock.now()
    with scope() as session:
        job = session.get(Job, job_id, with_for_update=True)
        if job is None:  # pragma: no cover
            return
        # Only the exception type: messages can contain user data.
        job.last_error = type(exc).__name__[:500]
        job.locked_by = None
        job.locked_at = None
        job.updated_at = now
        if job.attempts >= job.max_attempts:
            job.status = "dead"
        else:
            job.status = "failed"
            job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts, rand))
        session.commit()
        logger.warning(
            "job_failed",
            extra={"kind": job.kind, "job_id": str(job_id), "status": job.status,
                   "attempts": job.attempts, "error_type": job.last_error},
        )  # fmt: skip


def process_available(
    scope: SessionScope,
    handlers: dict[str, Handler],
    worker_id: str,
    clock: Clock,
    *,
    max_jobs: int = 100,
) -> int:
    """Run jobs until none is ready (or ``max_jobs``). Returns how many ran."""
    ran = 0
    while ran < max_jobs and run_one(scope, handlers, worker_id, clock) is not None:
        ran += 1
    return ran


def session_scope_from(factory: Callable[[], Session]) -> SessionScope:
    from contextlib import contextmanager

    @contextmanager
    def scope() -> Iterator[Session]:
        with factory() as session:
            yield session

    return scope
