"""The user's categories."""

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.repositories import categories as repo
from app.schemas.categories import CategoryCreate, CategoryList, CategoryOut, CategoryUpdate
from app.services import categories as service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=CategoryList)
def list_categories(
    user: CurrentUser, session: DbSession, include_archived: bool = False
) -> CategoryList:
    rows = repo.list_categories(session, user.id, include_archived=include_archived)
    return CategoryList(items=[CategoryOut.model_validate(c) for c in rows])


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreate, user: CurrentUser, session: DbSession) -> CategoryOut:
    return CategoryOut.model_validate(service.create_category(session, user.id, body))


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: UUID, body: CategoryUpdate, user: CurrentUser, session: DbSession
) -> CategoryOut:
    return CategoryOut.model_validate(service.update_category(session, user.id, category_id, body))
