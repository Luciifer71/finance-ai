"""Transfers between the user's own accounts (handoff 6.4 and 6.6).

A transfer is two rows (money out of one account, into another) sharing a
``transfer_group_id``. Transfers never count as spending or income.

- Suggestions: a debit and a credit in two different accounts, equal amounts,
  dated within 3 days, neither already paired.
- Automatic pairing (actor ``system``) only when a row has exactly one
  candidate, that candidate has exactly one candidate too, and a description
  carries a self-transfer hint (SELF, OWN A/C, OWN ACCOUNT, or the other
  account's last 4 digits). Everything else is only suggested.
- Unpairing restores each row's previous type and category from its audit event.
"""

import hashlib
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, not_, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.errors import NotFoundError, ProblemError
from app.domain.defaults import CASH_WITHDRAWAL
from app.domain.merchant import contains_word
from app.models import Category, FinancialAccount, Transaction, TransactionEvent
from app.repositories.common import get_owned_or_404
from app.services.ledger import Actor, apply_change

MAX_DAYS_APART = 3
SELF_HINTS = ("SELF", "OWN A/C", "OWN ACCOUNT")
CASH_PATTERN = re.compile(r"(?<![A-Z])(ATM|CASH WDL|CASH WITHDRAWAL|NWD)(?![A-Z])")
CASH_SOURCE = "cash_withdrawal"


@dataclass(frozen=True)
class Candidate:
    debit: Transaction
    credit: Transaction
    days_apart: int
    has_hint: bool


def _pairable(tx: type[Transaction], direction: str) -> list[ColumnElement[bool]]:
    """Conditions for a row that may become one side of a transfer."""
    allowed_types = ("expense",) if direction == "debit" else ("income", "refund")
    refund = aliased(Transaction)
    return [
        tx.direction == direction,
        tx.transaction_type.in_(allowed_types),
        tx.transfer_group_id.is_(None),
        tx.refund_of_id.is_(None),
        not_(exists().where(refund.refund_of_id == tx.id, refund.user_id == tx.user_id)),
    ]


def candidate_pairs(
    session: Session, user_id: UUID, touching: Iterable[UUID] | None = None
) -> list[Candidate]:
    debit, credit = aliased(Transaction), aliased(Transaction)
    statement = select(debit, credit).where(
        debit.user_id == user_id,
        credit.user_id == user_id,
        debit.amount == credit.amount,
        debit.account_id != credit.account_id,
        func.abs(debit.posted_on - credit.posted_on) <= MAX_DAYS_APART,
        *_pairable(debit, "debit"),
        *_pairable(credit, "credit"),
    )
    if touching is not None:
        ids = list(touching)
        statement = statement.where(or_(debit.id.in_(ids), credit.id.in_(ids)))
    statement = statement.order_by(debit.posted_on.desc(), debit.id, credit.id)
    rows = session.execute(statement).all()
    last4 = _last4_by_account(session, user_id)
    return [
        Candidate(
            debit=d,
            credit=c,
            days_apart=abs((d.posted_on - c.posted_on).days),
            has_hint=_has_self_hint(d, c, last4),
        )
        for d, c in rows
    ]


def _last4_by_account(session: Session, user_id: UUID) -> dict[UUID, str]:
    rows = session.execute(
        select(FinancialAccount.id, FinancialAccount.last4).where(
            FinancialAccount.user_id == user_id, FinancialAccount.last4.is_not(None)
        )
    ).all()
    return {row.id: row.last4 for row in rows}


def _has_self_hint(debit: Transaction, credit: Transaction, last4: dict[UUID, str]) -> bool:
    for tx, other in ((debit, credit), (credit, debit)):
        text = tx.description or ""
        if any(contains_word(text, hint) for hint in SELF_HINTS):
            return True
        other_last4 = last4.get(other.account_id)
        if other_last4 and contains_word(text, other_last4):
            return True
    return False


# --- pairing ----------------------------------------------------------------------------------


def _lock_pair(
    session: Session, user_id: UUID, debit_id: UUID, credit_id: UUID
) -> tuple[Transaction, Transaction]:
    # Lock in id order so two concurrent requests cannot deadlock.
    rows = session.scalars(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.id.in_([debit_id, credit_id]))
        .order_by(Transaction.id)
        .with_for_update()
    ).all()
    by_id = {row.id: row for row in rows}
    if debit_id not in by_id or credit_id not in by_id:
        raise NotFoundError("transaction")
    return by_id[debit_id], by_id[credit_id]


def _refund_links(session: Session, tx: Transaction) -> bool:
    return (
        session.scalar(
            select(
                exists().where(Transaction.refund_of_id == tx.id, Transaction.user_id == tx.user_id)
            )
        )
        or tx.refund_of_id is not None
    )


def _check_pairable(session: Session, debit: Transaction, credit: Transaction) -> None:
    def problem(status: int, code: str, title: str, detail: str) -> ProblemError:
        return ProblemError(status, code, title, detail)

    if debit.id == credit.id:
        raise problem(422, "transfer.same_transaction", "Invalid pair", "Choose two transactions.")
    if debit.direction != "debit" or credit.direction != "credit":
        raise problem(
            422, "transfer.wrong_directions", "Invalid pair",
            "A transfer needs one money-out (debit) and one money-in (credit) transaction.",
        )  # fmt: skip
    if debit.amount != credit.amount:
        raise problem(
            422, "transfer.amount_mismatch", "Invalid pair", "Both sides must have the same amount."
        )
    if debit.account_id == credit.account_id:
        raise problem(
            422, "transfer.same_account", "Invalid pair", "A transfer needs two different accounts."
        )
    if debit.transfer_group_id is not None or credit.transfer_group_id is not None:
        raise problem(
            409, "transfer.already_paired", "Already paired", "A transaction is already paired."
        )
    if _refund_links(session, debit) or _refund_links(session, credit):
        raise problem(
            409, "transfer.has_refund_link", "Linked to a refund",
            "A transaction linked as a refund (or refunded) cannot be a transfer.",
        )  # fmt: skip


def pair(
    session: Session,
    user_id: UUID,
    debit_id: UUID,
    credit_id: UUID,
    *,
    actor: Actor = "user",
    reason: str | None = None,
    commit: bool = True,
) -> UUID:
    debit, credit = _lock_pair(session, user_id, debit_id, credit_id)
    _check_pairable(session, debit, credit)
    group_id = uuid.uuid4()
    for tx in (debit, credit):
        apply_change(
            session,
            tx,
            {
                "transaction_type": "transfer",
                "transfer_group_id": group_id,
                "category_id": None,
                "category_source": "none",
            },
            event_type="transfer_paired",
            actor=actor,
            reason=reason,
        )
    if commit:
        session.commit()
    return group_id


def unpair(session: Session, user_id: UUID, group_id: UUID) -> list[Transaction]:
    rows = list(
        session.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.transfer_group_id == group_id)
            .order_by(Transaction.id)
            .with_for_update()
        )
    )
    if not rows:
        raise NotFoundError("transfer")
    if any(row.source == CASH_SOURCE for row in rows):
        raise ProblemError(
            409,
            "transfer.cash_withdrawal_cannot_unpair",
            "Cannot unpair",
            "A confirmed cash withdrawal created the cash side of this transfer, and transactions "
            "cannot be deleted. Record a balance adjustment on the cash account instead.",
        )
    for tx in rows:
        before = _paired_from(session, tx)
        default_type = "expense" if tx.direction == "debit" else "income"
        apply_change(
            session,
            tx,
            {
                "transaction_type": before.get("transaction_type", default_type),
                "transfer_group_id": None,
                "category_id": _uuid_or_none(before.get("category_id")),
                "category_source": before.get("category_source", "none"),
            },
            event_type="transfer_unpaired",
            actor="user",
        )
    session.commit()
    return rows


def _paired_from(session: Session, tx: Transaction) -> dict[str, object]:
    """The editable fields as they were just before this row was last paired."""
    event = session.scalars(
        select(TransactionEvent)
        .where(
            TransactionEvent.transaction_id == tx.id,
            TransactionEvent.user_id == tx.user_id,
            TransactionEvent.event_type == "transfer_paired",
        )
        .order_by(TransactionEvent.seq.desc())
        .limit(1)
    ).first()
    return dict(event.before) if event else {}


def _uuid_or_none(value: object) -> UUID | None:
    return UUID(str(value)) if value else None


def auto_pair(session: Session, user_id: UUID, new_ids: Iterable[UUID]) -> list[UUID]:
    """Pair new rows automatically where it is unambiguous (see module docstring).
    Does not commit; runs inside the caller's transaction."""
    ids = list(new_ids)
    if not ids:
        return []
    first = candidate_pairs(session, user_id, touching=ids)
    involved = {c.debit.id for c in first} | {c.credit.id for c in first}
    candidates = candidate_pairs(session, user_id, touching=involved) if involved else []
    per_row: dict[UUID, int] = defaultdict(int)
    for c in candidates:
        per_row[c.debit.id] += 1
        per_row[c.credit.id] += 1
    groups: list[UUID] = []
    done: set[UUID] = set()
    for c in first:
        if not c.has_hint or c.debit.id in done or c.credit.id in done:
            continue
        if per_row[c.debit.id] == 1 and per_row[c.credit.id] == 1:
            groups.append(
                pair(
                    session,
                    user_id,
                    c.debit.id,
                    c.credit.id,
                    actor="system",
                    reason="single candidate with a self-transfer hint",
                    commit=False,
                )
            )
            done |= {c.debit.id, c.credit.id}
    return groups


# --- cash withdrawals -------------------------------------------------------------------------


def group_rows(session: Session, user_id: UUID, group_id: UUID) -> list[Transaction]:
    """Both sides of a transfer, debit first."""
    return list(
        session.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.transfer_group_id == group_id)
            .order_by(Transaction.direction.desc())
        )
    )


CashAction = Literal[
    "transfer_to_cash_account", "categorize_as_cash_withdrawal", "choose_cash_account"
]


@dataclass(frozen=True)
class CashSuggestion:
    transaction: Transaction
    action: CashAction
    cash_account_ids: list[UUID]
    category_id: UUID | None


def cash_withdrawal_suggestions(session: Session, user_id: UUID) -> list[CashSuggestion]:
    cash_accounts = list(
        session.scalars(
            select(FinancialAccount.id).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.account_type == "cash",
                FinancialAccount.is_archived.is_(False),
            )
        )
    )
    category_id = session.scalar(
        select(Category.id).where(Category.user_id == user_id, Category.name == CASH_WITHDRAWAL)
    )
    rows = session.scalars(
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.is_excluded.is_(False),
            *_pairable(Transaction, "debit"),
        )
        .order_by(Transaction.posted_on.desc(), Transaction.id.desc())
    ).all()
    suggestions = []
    for tx in rows:
        if not CASH_PATTERN.search((tx.description or "").upper()):
            continue
        others = [a for a in cash_accounts if a != tx.account_id]
        action: CashAction
        if len(others) == 1:
            action = "transfer_to_cash_account"
        elif not others:
            if tx.category_id == category_id:
                continue  # already categorized as a cash withdrawal
            action = "categorize_as_cash_withdrawal"
        else:
            action = "choose_cash_account"
        suggestions.append(
            CashSuggestion(
                transaction=tx,
                action=action,
                cash_account_ids=others,
                category_id=category_id if action == "categorize_as_cash_withdrawal" else None,
            )
        )
    return suggestions


def confirm_cash_withdrawal(
    session: Session, user_id: UUID, transaction_id: UUID, cash_account_id: UUID
) -> UUID:
    """Record the cash arriving in the wallet and pair it with the bank withdrawal."""
    debit = get_owned_or_404(
        session, Transaction, transaction_id, user_id, "transaction", for_update=True
    )
    cash = get_owned_or_404(session, FinancialAccount, cash_account_id, user_id, "account")
    if cash.account_type != "cash" or cash.is_archived:
        raise ProblemError(
            422,
            "transfer.not_a_cash_account",
            "Not a cash account",
            "Choose an active cash account.",
        )
    credit_id = uuid.uuid4()
    credit = Transaction(
        id=credit_id,
        user_id=user_id,
        account_id=cash.id,
        amount=debit.amount,
        direction="credit",
        transaction_type="income",
        description="Cash withdrawal received",
        source=CASH_SOURCE,
        # One cash-side row per withdrawal: confirming twice is a conflict, not a duplicate.
        fingerprint=hashlib.sha256(f"{CASH_SOURCE}{debit.id}".encode()).hexdigest(),
        posted_on=debit.posted_on,
    )
    _check_pairable(session, debit, credit)
    session.add(credit)
    session.flush()
    return pair(session, user_id, debit.id, credit_id, actor="user", reason="cash withdrawal")
