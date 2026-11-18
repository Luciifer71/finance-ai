"""Editing transactions, with an audit event for every change (handoff 6.7).

Only the editable fields can change: category, type, transfer group, refund
link, notes and the excluded flag. Source facts (amount, date, description,
...) are protected by a database trigger as well. Each change writes exactly
one ``transaction_events`` row in the same database transaction, holding the
changed fields before and after.
"""

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.models import Category, Transaction, TransactionEvent
from app.repositories.common import get_owned_or_404
from app.services.transactions import check_category_for

Actor = Literal["user", "system", "rule"]
EDITABLE_FIELDS = (
    "category_id",
    "category_source",
    "transaction_type",
    "transfer_group_id",
    "refund_of_id",
    "notes",
    "is_excluded",
)
_EVENT_FOR_FIELD = {
    "category_id": "category_changed",
    "notes": "notes_changed",
    "is_excluded": "exclusion_changed",
    "transaction_type": "type_changed",
}


def _json(value: object) -> object:
    return str(value) if isinstance(value, UUID) else value


def editable_state(tx: Transaction) -> dict[str, Any]:
    return {name: _json(getattr(tx, name)) for name in EDITABLE_FIELDS}


def apply_change(
    session: Session,
    tx: Transaction,
    changes: dict[str, Any],
    *,
    event_type: str | None,
    actor: Actor,
    reason: str | None = None,
) -> TransactionEvent | None:
    """Set ``changes`` on ``tx`` and record one event with only the fields that changed.
    Returns None (and writes nothing) if nothing actually changed."""
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    before_all = editable_state(tx)
    for name, value in changes.items():
        setattr(tx, name, value)
    after_all = editable_state(tx)
    changed = [name for name in EDITABLE_FIELDS if before_all[name] != after_all[name]]
    if not changed:
        return None
    if event_type is None:
        user_fields = [name for name in changed if name != "category_source"]
        event_type = (
            _EVENT_FOR_FIELD.get(user_fields[0], "edited") if len(user_fields) == 1 else "edited"
        )
    event = TransactionEvent(
        user_id=tx.user_id,
        transaction_id=tx.id,
        event_type=event_type,
        before={name: before_all[name] for name in changed},
        after={name: after_all[name] for name in changed},
        actor=actor,
        reason=reason,
    )
    session.add(event)
    session.flush()
    return event


def lock_transaction(session: Session, user_id: UUID, transaction_id: UUID) -> Transaction:
    return get_owned_or_404(
        session, Transaction, transaction_id, user_id, "transaction", for_update=True
    )


def update_transaction(
    session: Session, user_id: UUID, transaction_id: UUID, fields: dict[str, Any]
) -> Transaction:
    """PATCH /transactions/{id}. ``fields`` holds only what the client sent."""
    tx = lock_transaction(session, user_id, transaction_id)
    changes: dict[str, Any] = {}

    new_type = fields.get("transaction_type")
    if new_type is not None and new_type != tx.transaction_type:
        changes.update(_type_change(session, user_id, tx, new_type))

    if "category_id" in fields:
        changes.update(_category_change(session, user_id, tx, fields["category_id"], changes))

    if "notes" in fields:
        notes = (fields["notes"] or "").strip()
        changes["notes"] = notes or None
    if fields.get("is_excluded") is not None:
        changes["is_excluded"] = fields["is_excluded"]

    apply_change(session, tx, changes, event_type=None, actor="user")
    session.commit()
    return tx


def _type_change(session: Session, user_id: UUID, tx: Transaction, new_type: str) -> dict[str, Any]:
    if tx.transaction_type == "transfer":
        raise ProblemError(
            409,
            "transaction.is_transfer",
            "Transaction is a transfer",
            "Unpair the transfer first, then change its type.",
        )
    if new_type == "transfer":
        raise ProblemError(
            422,
            "transaction.use_transfer_pairing",
            "Use transfer pairing",
            "Transfers are made by pairing two transactions.",
        )
    allowed = {"debit": {"expense"}, "credit": {"income", "refund"}}[tx.direction]
    if new_type not in allowed:
        raise ProblemError(
            422,
            "transaction.type_direction_mismatch",
            "Type does not match direction",
            "Expenses are debits; income and refunds are credits.",
        )
    changes: dict[str, Any] = {"transaction_type": new_type}
    if new_type != "refund":
        changes["refund_of_id"] = None
    # A category of the wrong kind for the new type is cleared (and recorded in the event).
    if tx.category_id is not None:
        category = session.get(Category, tx.category_id)
        expected = "income" if new_type == "income" else "expense"
        if category is not None and category.kind != expected:
            changes["category_id"] = None
            changes["category_source"] = "none"
    return changes


def _category_change(
    session: Session,
    user_id: UUID,
    tx: Transaction,
    category_id: UUID | None,
    pending: dict[str, Any],
) -> dict[str, Any]:
    transaction_type = pending.get("transaction_type", tx.transaction_type)
    if category_id is None:
        return {"category_id": None, "category_source": "user"}
    if transaction_type == "transfer":
        raise ProblemError(
            422,
            "transaction.transfer_has_no_category",
            "Transfers have no category",
            "Moving money between your own accounts is not spending.",
        )
    check_category_for(session, user_id, category_id, transaction_type)
    return {"category_id": category_id, "category_source": "user"}


def list_events(session: Session, user_id: UUID, transaction_id: UUID) -> list[TransactionEvent]:
    get_owned_or_404(session, Transaction, transaction_id, user_id, "transaction")
    return list(
        session.scalars(
            select(TransactionEvent)
            .where(
                TransactionEvent.user_id == user_id,
                TransactionEvent.transaction_id == transaction_id,
            )
            .order_by(TransactionEvent.seq)
        )
    )
