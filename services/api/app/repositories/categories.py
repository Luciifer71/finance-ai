"""User-scoped queries for categories."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category


def list_categories(session: Session, user_id: UUID, *, include_archived: bool) -> list[Category]:
    statement = select(Category).where(Category.user_id == user_id)
    if not include_archived:
        statement = statement.where(Category.is_archived.is_(False))
    return list(session.scalars(statement.order_by(Category.kind, Category.name)))


def find_by_name(session: Session, user_id: UUID, name: str) -> Category | None:
    """Case-insensitive name lookup within one user's categories."""
    return session.scalars(
        select(Category).where(
            Category.user_id == user_id, func.lower(Category.name) == name.lower()
        )
    ).first()
