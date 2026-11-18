"""Categories: create, rename, archive. ``Uncategorized`` is protected."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.domain.defaults import UNCATEGORIZED
from app.models import Category
from app.repositories import categories as repo
from app.repositories.common import get_owned_or_404
from app.schemas.categories import CategoryCreate, CategoryUpdate


def _name_taken(session: Session, user_id: UUID, name: str, except_id: UUID | None) -> bool:
    existing = repo.find_by_name(session, user_id, name)
    return existing is not None and existing.id != except_id


def _conflict() -> ProblemError:
    return ProblemError(
        409,
        "category.name_taken",
        "Name already used",
        "You already have a category with this name.",
    )


def create_category(session: Session, user_id: UUID, data: CategoryCreate) -> Category:
    if _name_taken(session, user_id, data.name, None):
        raise _conflict()
    category = Category(user_id=user_id, name=data.name, kind=data.kind)
    session.add(category)
    session.commit()
    return category


def update_category(
    session: Session, user_id: UUID, category_id: UUID, data: CategoryUpdate
) -> Category:
    category = get_owned_or_404(
        session, Category, category_id, user_id, "category", for_update=True
    )
    protected = category.name == UNCATEGORIZED
    if data.name is not None and data.name != category.name:
        if protected:
            raise ProblemError(
                409,
                "category.protected",
                "Category is protected",
                f"'{UNCATEGORIZED}' cannot be renamed or archived.",
            )
        if _name_taken(session, user_id, data.name, category.id):
            raise _conflict()
        category.name = data.name
    if data.is_archived is not None:
        if protected and data.is_archived:
            raise ProblemError(
                409,
                "category.protected",
                "Category is protected",
                f"'{UNCATEGORIZED}' cannot be renamed or archived.",
            )
        category.is_archived = data.is_archived
    session.commit()
    return category
