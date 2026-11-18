from typing import Annotated, Literal
from uuid import UUID

from pydantic import StringConstraints

from app.schemas.common import ApiModel, UtcDatetime

CategoryKind = Literal["expense", "income"]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class CategoryCreate(ApiModel):
    name: CategoryName
    kind: CategoryKind


class CategoryUpdate(ApiModel):
    name: CategoryName | None = None
    is_archived: bool | None = None


class CategoryOut(ApiModel):
    id: UUID
    name: str
    kind: CategoryKind
    is_archived: bool
    created_at: UtcDatetime


class CategoryList(ApiModel):
    items: list[CategoryOut]
