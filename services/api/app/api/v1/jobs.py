"""Status of background work the user started (e.g. categorizing an import)."""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.models import Job
from app.repositories.common import get_owned_or_404
from app.schemas.jobs import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def read_job(job_id: UUID, user: CurrentUser, session: DbSession) -> JobOut:
    return JobOut.model_validate(get_owned_or_404(session, Job, job_id, user.id, "job"))
