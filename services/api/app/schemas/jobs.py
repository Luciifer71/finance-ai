from typing import Literal
from uuid import UUID

from app.schemas.common import ApiModel, UtcDatetime


class JobOut(ApiModel):
    id: UUID
    kind: str
    status: Literal["queued", "running", "succeeded", "failed", "dead"]
    attempts: int
    max_attempts: int
    run_after: UtcDatetime
    created_at: UtcDatetime
    updated_at: UtcDatetime
    last_error: str | None
