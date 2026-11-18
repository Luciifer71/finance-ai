"""Test-only: load an export zip into an empty database (handoff 12, restore test).

Not part of the app on purpose: users cannot upload exports. This exists to prove
an export holds everything needed to rebuild the user's data exactly.
"""

import io
import json
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import (
    BalanceSnapshot,
    Budget,
    Category,
    FinancialAccount,
    Goal,
    GoalEvent,
    Transaction,
    TransactionEvent,
    TransactionImport,
    User,
)
from app.services.export import read_transactions_csv


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _money(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def restore(session: Session, files: dict[str, bytes], email: str) -> uuid.UUID:
    """Insert everything from an export as a new user. Returns the new user's id."""
    user = User(id=uuid.uuid4(), auth_subject=str(uuid.uuid4()), email=email)
    session.add(user)
    session.flush()
    uid = user.id

    def load(name: str) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = json.loads(files[name])
        return data

    def rows(model: Any, items: list[dict[str, Any]]) -> None:
        if items:
            session.execute(insert(model), items)

    rows(
        Category,
        [
            {
                "id": _uuid(c["id"]),
                "user_id": uid,
                "name": c["name"],
                "kind": c["kind"],
                "is_archived": c["is_archived"],
                "created_at": _ts(c["created_at"]),
            }
            for c in load("categories.json")
        ],
    )
    accounts = load("accounts.json")
    rows(
        FinancialAccount,
        [
            {
                "id": _uuid(a["id"]),
                "user_id": uid,
                "name": a["name"],
                "account_type": a["account_type"],
                "institution": a["institution"],
                "currency": a["currency"],
                "last4": a["last4"],
                "is_archived": a["is_archived"],
                "created_at": _ts(a["created_at"]),
            }
            for a in accounts
        ],
    )
    rows(
        TransactionImport,
        [
            {
                "id": _uuid(i["id"]),
                "user_id": uid,
                "account_id": _uuid(i["account_id"]),
                "source": i["source"],
                "profile_id": i["profile_id"],
                "file_sha256": i["file_sha256"],
                "file_size_bytes": i["file_size_bytes"],
                "status": i["status"],
                "rows_total": i["rows_total"],
                "rows_imported": i["rows_imported"],
                "rows_skipped": i["rows_skipped"],
                "rows_failed": i["rows_failed"],
                "date_from": _date(i["date_from"]),
                "date_to": _date(i["date_to"]),
                "closing_balance": _money(i["closing_balance"]),
                "closing_balance_on": _date(i["closing_balance_on"]),
                "warnings": i["warnings"],
                "error_message": i["error_message"],
                "created_at": _ts(i["created_at"]),
                "completed_at": _ts(i["completed_at"]),
            }
            for i in load("imports.json")
        ],
    )
    rows(
        BalanceSnapshot,
        [
            {
                "id": _uuid(s["id"]),
                "user_id": uid,
                "account_id": _uuid(s["account_id"]),
                "import_id": _uuid(s["import_id"]),
                "as_of": _date(s["as_of"]),
                "balance": _money(s["balance"]),
                "source": s["source"],
                "created_at": _ts(s["created_at"]),
            }
            for a in accounts
            for s in a["balance_snapshots"]
        ],
    )
    transactions = read_transactions_csv(files["transactions.csv"])
    # Originals before the refunds that point at them (self-referencing foreign key).
    transactions.sort(key=lambda t: t["refund_of_id"] is not None)
    rows(
        Transaction,
        [
            {
                "id": _uuid(t["id"]),
                "user_id": uid,
                "account_id": _uuid(t["account_id"]),
                "posted_on": _date(t["posted_on"]),
                "occurred_at": _ts(t["occurred_at"]),
                "amount": _money(t["amount"]),
                "direction": t["direction"],
                "transaction_type": t["transaction_type"],
                "category_id": _uuid(t["category_id"]),
                "category_source": t["category_source"],
                "description": t["description"],
                "notes": t["notes"],
                "is_excluded": t["is_excluded"] == "true",
                "source": t["source"],
                "external_id": t["external_id"],
                "fingerprint": t["fingerprint"],
                "import_id": _uuid(t["import_id"]),
                "import_row_number": int(t["import_row_number"])
                if t["import_row_number"]
                else None,
                "transfer_group_id": _uuid(t["transfer_group_id"]),
                "refund_of_id": _uuid(t["refund_of_id"]),
                "created_at": _ts(t["created_at"]),
            }
            for t in transactions
        ],
    )
    rows(
        TransactionEvent,
        [
            {
                "id": _uuid(e["id"]),
                "user_id": uid,
                "transaction_id": _uuid(e["transaction_id"]),
                "event_type": e["event_type"],
                "before": e["before"],
                "after": e["after"],
                "actor": e["actor"],
                "reason": e["reason"],
                "created_at": _ts(e["created_at"]),
            }
            for e in load("transaction_events.json")
        ],
    )
    rows(
        Budget,
        [
            {
                "id": _uuid(b["id"]),
                "user_id": uid,
                "category_id": _uuid(b["category_id"]),
                "month": _date(b["month"]),
                "amount": _money(b["amount"]),
                "warn_at_percent": b["warn_at_percent"],
                "created_at": _ts(b["created_at"]),
                "updated_at": _ts(b["updated_at"]),
            }
            for b in load("budgets.json")
        ],
    )
    goals = load("goals.json")
    rows(
        Goal,
        [
            {
                "id": _uuid(g["id"]),
                "user_id": uid,
                "name": g["name"],
                "kind": g["kind"],
                "target_amount": _money(g["target_amount"]),
                "target_date": _date(g["target_date"]),
                "item_url": g["item_url"],
                "priority": g["priority"],
                "status": g["status"],
                "created_at": _ts(g["created_at"]),
                "updated_at": _ts(g["updated_at"]),
            }
            for g in goals
        ],
    )
    rows(
        GoalEvent,
        [
            {
                "id": _uuid(e["id"]),
                "user_id": uid,
                "goal_id": _uuid(g["id"]),
                "event_type": e["event_type"],
                "amount": _money(e["amount"]),
                "before": e["before"],
                "after": e["after"],
                "note": e["note"],
                "actor": e["actor"],
                "created_at": _ts(e["created_at"]),
            }
            for g in goals
            for e in g["events"]
        ],
    )
    session.commit()
    return uid
