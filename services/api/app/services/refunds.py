"""Refunds and their link to the original purchase (handoff 6.4 and 6.5).

A refund is money back for an earlier expense. Linking it to the original
makes reports reduce the original's category. Limits: one refund can be at
most the original's amount, and all refunds of one original together can be
at most the original's amount (exactly equal is allowed; one paisa more is
not). The original row is locked while checking, so two refunds linked at the
same moment cannot both squeeze under the limit.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.domain.merchant import normalize_merchant
from app.models import Category, Transaction
from app.repositories.common import get_owned_or_404
from app.services.ledger import apply_change

WINDOW_DAYS = 60
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class RefundSuggestion:
    refund: Transaction
    original: Transaction
    merchant: str


def refunded_so_far(session: Session, user_id: UUID, original_id: UUID) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id, Transaction.refund_of_id == original_id
        )
    )
    return Decimal(total or 0)


def suggestions(session: Session, user_id: UUID) -> list[RefundSuggestion]:
    credits = session.scalars(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.direction == "credit",
            Transaction.transaction_type.in_(("income", "refund")),
            Transaction.refund_of_id.is_(None),
            Transaction.transfer_group_id.is_(None),
            Transaction.is_excluded.is_(False),
        )
    ).all()
    if not credits:
        return []
    earliest = min(c.posted_on for c in credits) - timedelta(days=WINDOW_DAYS)
    expenses = session.scalars(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "expense",
            Transaction.posted_on >= earliest,
        )
        .order_by(Transaction.posted_on.desc(), Transaction.created_at.desc())
    ).all()
    refunded: dict[UUID, Decimal] = {
        row.refund_of_id: row.total
        for row in session.execute(
            select(Transaction.refund_of_id, func.sum(Transaction.amount).label("total"))
            .where(Transaction.user_id == user_id, Transaction.refund_of_id.is_not(None))
            .group_by(Transaction.refund_of_id)
        )
        if row.refund_of_id is not None
    }

    found = []
    for credit in sorted(credits, key=lambda c: (c.posted_on, c.id), reverse=True):
        merchant = normalize_merchant(credit.description)
        if not merchant:
            continue
        for expense in expenses:  # newest first: the most recent match wins
            if (
                expense.account_id == credit.account_id
                and credit.posted_on - timedelta(days=WINDOW_DAYS)
                <= expense.posted_on
                <= credit.posted_on
                and credit.amount <= expense.amount - refunded.get(expense.id, ZERO)
                and normalize_merchant(expense.description) == merchant
            ):
                found.append(RefundSuggestion(refund=credit, original=expense, merchant=merchant))
                break
    return found


def link(session: Session, user_id: UUID, refund_id: UUID, original_id: UUID) -> Transaction:
    if refund_id == original_id:
        raise ProblemError(
            422, "refund.same_transaction", "Invalid refund", "A refund cannot refund itself."
        )
    # Lock the original first: every link to it is serialized on this row.
    original = get_owned_or_404(
        session, Transaction, original_id, user_id, "transaction", for_update=True
    )
    refund = get_owned_or_404(
        session, Transaction, refund_id, user_id, "transaction", for_update=True
    )
    if original.transaction_type != "expense":
        raise ProblemError(
            422,
            "refund.original_not_expense",
            "Invalid refund",
            "Only an expense can be refunded.",
        )
    if refund.direction != "credit" or refund.transfer_group_id is not None:
        raise ProblemError(
            422,
            "refund.not_a_credit",
            "Invalid refund",
            "A refund is money coming in that is not a transfer.",
        )
    if refund.refund_of_id is not None:
        if refund.refund_of_id == original.id:
            return refund  # already linked to this original: nothing to do
        raise ProblemError(
            409, "refund.already_linked", "Already linked", "This refund is linked elsewhere."
        )
    already = refunded_so_far(session, user_id, original.id)
    if refund.amount > original.amount or already + refund.amount > original.amount:
        raise ProblemError(
            422,
            "refund.exceeds_original",
            "Refund too large",
            "Refunds of one purchase cannot add up to more than the purchase.",
            extra={
                "original_amount": format(original.amount, "f"),
                "already_refunded": format(already, "f"),
            },
        )

    changes: dict[str, object] = {"transaction_type": "refund", "refund_of_id": original.id}
    if refund.category_id is not None:
        category = session.get(Category, refund.category_id)
        if category is not None and category.kind != "expense":
            changes.update(category_id=None, category_source="none")
    apply_change(session, refund, changes, event_type="refund_linked", actor="user")
    session.commit()
    return refund
