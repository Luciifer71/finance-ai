"""The one way to fetch a user-owned row by id.

Every lookup filters by ``user_id`` as well as ``id``. Another user's row and a
row that does not exist look exactly the same to the caller: 404.
"""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import Base


def get_owned[T: Base](session: Session, model: type[T], row_id: UUID, user_id: UUID) -> T | None:
    columns = cast(Any, model)
    row: T | None = session.scalars(
        select(model).where(columns.id == row_id, columns.user_id == user_id)
    ).first()
    return row


def get_owned_or_404[T: Base](
    session: Session,
    model: type[T],
    row_id: UUID,
    user_id: UUID,
    resource: str,
    *,
    for_update: bool = False,
) -> T:
    columns = cast(Any, model)
    statement = select(model).where(columns.id == row_id, columns.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    row: T | None = session.scalars(statement).first()
    if row is None:
        raise NotFoundError(resource)
    return row
