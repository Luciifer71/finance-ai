"""Reading transactions and recording manual ones."""

import hashlib
import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.core.pagination import decode_cursor, encode_cursor
from app.models import Category, FinancialAccount, Transaction
from app.repositories import transactions as repo
from app.repositories.common import get_owned_or_404
from app.schemas.transactions import ManualTransactionCreate, TransactionOut


def signed_amount(tx: Transaction) -> Decimal:
    return tx.amount if tx.direction == "credit" else -tx.amount


def to_out(tx: Transaction) -> TransactionOut:
    return TransactionOut.model_validate(
        {
            "id": tx.id,
            "account_id": tx.account_id,
            "import_id": tx.import_id,
            "category_id": tx.category_id,
            "amount": tx.amount,
            "signed_amount": signed_amount(tx),
            "direction": tx.direction,
            "transaction_type": tx.transaction_type,
            "description": tx.description,
            "source": tx.source,
            "posted_on": tx.posted_on,
            "occurred_at": tx.occurred_at,
            "transfer_group_id": tx.transfer_group_id,
            "refund_of_id": tx.refund_of_id,
            "created_at": tx.created_at,
        }
    )


def list_transactions(
    session: Session,
    user_id: UUID,
    filters: repo.TransactionFilters,
    *,
    limit: int,
    cursor: str | None,
) -> tuple[list[Transaction], str | None]:
    after = decode_cursor(cursor) if cursor else None
    rows = repo.list_page(session, user_id, filters, limit=limit, after=after)
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].posted_on, rows[-1].id) if has_more and rows else None
    return rows, next_cursor


def get_transaction(session: Session, user_id: UUID, transaction_id: UUID) -> Transaction:
    return get_owned_or_404(session, Transaction, transaction_id, user_id, "transaction")


def check_category_for(
    session: Session, user_id: UUID, category_id: UUID, transaction_type: str
) -> Category:
    """A category must be the user's own, active, and of the matching kind.

    Expenses and refunds use expense categories (a refund reduces spending in its
    category); income uses income categories; transfers have no category.
    """
    category = get_owned_or_404(session, Category, category_id, user_id, "category")
    if category.is_archived:
        raise ProblemError(
            409, "category.archived", "Category archived", "This category is archived."
        )
    expected = {"expense": "expense", "refund": "expense", "income": "income"}.get(transaction_type)
    if expected is None or category.kind != expected:
        raise ProblemError(
            422,
            "transaction.category_kind_mismatch",
            "Category does not fit",
            f"A {transaction_type} needs an {expected or 'no'} category.",
        )
    return category


def create_manual(session: Session, user_id: UUID, data: ManualTransactionCreate) -> Transaction:
    account = get_owned_or_404(session, FinancialAccount, data.account_id, user_id, "account")
    if account.is_archived:
        raise ProblemError(409, "account.archived", "Account archived", "This account is archived.")
    if data.amount <= 0:
        raise ProblemError(
            422, "transaction.amount_not_positive", "Invalid amount", "Amount must be positive."
        )
    transaction_type = data.transaction_type or (
        "expense" if data.direction == "debit" else "income"
    )
    if (transaction_type == "expense") != (data.direction == "debit"):
        raise ProblemError(
            422,
            "transaction.type_direction_mismatch",
            "Type does not match direction",
            "Expenses are debits; income and refunds are credits.",
        )
    if data.category_id is not None:
        check_category_for(session, user_id, data.category_id, transaction_type)

    row_id = uuid.uuid4()
    tx = Transaction(
        id=row_id,
        user_id=user_id,
        account_id=account.id,
        category_id=data.category_id,
        amount=data.amount,
        direction=data.direction,
        transaction_type=transaction_type,
        description=data.description,
        source="manual",
        # Section 6.7: manual rows are unique by construction.
        fingerprint=hashlib.sha256(f"manual{row_id}".encode()).hexdigest(),
        posted_on=data.posted_on,
        occurred_at=data.occurred_at,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx
