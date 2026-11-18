"""User-scoped transaction queries."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Transaction


@dataclass(frozen=True, slots=True)
class TransactionFilters:
    account_id: UUID | None = None
    category_id: UUID | None = None
    transaction_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    query: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    include_excluded: bool = False


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_page(
    session: Session,
    user_id: UUID,
    filters: TransactionFilters,
    *,
    limit: int,
    after: tuple[date, UUID] | None,
) -> list[Transaction]:
    """One page, newest first, ordered by (posted_on DESC, id DESC). Fetches limit + 1 rows
    so the caller knows whether another page exists."""
    statement = select(Transaction).where(Transaction.user_id == user_id)
    if filters.account_id is not None:
        statement = statement.where(Transaction.account_id == filters.account_id)
    if filters.category_id is not None:
        statement = statement.where(Transaction.category_id == filters.category_id)
    if filters.transaction_type is not None:
        statement = statement.where(Transaction.transaction_type == filters.transaction_type)
    if filters.date_from is not None:
        statement = statement.where(Transaction.posted_on >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(Transaction.posted_on <= filters.date_to)
    if filters.query:
        statement = statement.where(
            Transaction.description.ilike(f"%{_escape_like(filters.query)}%", escape="\\")
        )
    if filters.min_amount is not None:
        statement = statement.where(Transaction.amount >= filters.min_amount)
    if filters.max_amount is not None:
        statement = statement.where(Transaction.amount <= filters.max_amount)
    if not filters.include_excluded:
        statement = statement.where(Transaction.is_excluded.is_(False))
    if after is not None:
        posted_on, row_id = after
        statement = statement.where(
            or_(
                Transaction.posted_on < posted_on,
                and_(Transaction.posted_on == posted_on, Transaction.id < row_id),
            )
        )
    statement = statement.order_by(Transaction.posted_on.desc(), Transaction.id.desc())
    return list(session.scalars(statement.limit(limit + 1)))
