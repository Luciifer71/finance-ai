from uuid import UUID

from app.schemas.common import ApiModel, UtcDatetime


class MeResponse(ApiModel):
    id: UUID
    email: str
    created_at: UtcDatetime
