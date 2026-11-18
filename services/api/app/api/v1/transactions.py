"""Transactions: search, read, record manually."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ProblemError
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.domain.money import MoneyFormatError, parse_money
from app.repositories.transactions import TransactionFilters
from app.schemas.transactions import ManualTransactionCreate, TransactionOut, TransactionPage
from app.services import transactions as service

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _money_query(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return parse_money(value)
    except MoneyFormatError as exc:
        raise ProblemError(
            422,
            "request.validation_failed",
            "Validation failed",
            "One or more fields are invalid.",
            extra={"errors": [{"field": field, "message": str(exc)}]},
        ) from exc


@router.get("", response_model=TransactionPage)
def list_transactions(
    user: CurrentUser,
    session: DbSession,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    type: Literal["income", "expense", "transfer", "refund"] | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    min_amount: Annotated[str | None, Query(examples=["100.00"])] = None,
    max_amount: Annotated[str | None, Query(examples=["5000.00"])] = None,
    include_excluded: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> TransactionPage:
    """Newest first. Pass `next_cursor` from one page as `cursor` to get the next."""
    filters = TransactionFilters(
        account_id=account_id,
        category_id=category_id,
        transaction_type=type,
        date_from=from_,
        date_to=to,
        query=q,
        min_amount=_money_query(min_amount, "min_amount"),
        max_amount=_money_query(max_amount, "max_amount"),
        include_excluded=include_excluded,
    )
    rows, next_cursor = service.list_transactions(
        session, user.id, filters, limit=limit, cursor=cursor
    )
    return TransactionPage(items=[service.to_out(tx) for tx in rows], next_cursor=next_cursor)


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: ManualTransactionCreate, user: CurrentUser, session: DbSession
) -> TransactionOut:
    return service.to_out(service.create_manual(session, user.id, body))


@router.get("/{transaction_id}", response_model=TransactionOut)
def read_transaction(transaction_id: UUID, user: CurrentUser, session: DbSession) -> TransactionOut:
    return service.to_out(service.get_transaction(session, user.id, transaction_id))
