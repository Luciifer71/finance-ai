"""Export all of a user's data as a zip (handoff section 12).

Files: transactions.csv, accounts.json (with balance snapshots), categories.json,
budgets.json, goals.json, imports.json, transaction_events.json, manifest.json.
The manifest lists every file's row count and SHA-256, so an export can be
checked and two exports compared. Output is deterministic: the same data always
gives byte-identical files.

CSV formula injection: spreadsheet apps run cells that start with = + - @ tab or
CR as formulas. Every such text cell gets a leading apostrophe; a cell that
already starts with an apostrophe gets one too, so ``unescape_cell`` can always
undo it exactly.
"""

import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BalanceSnapshot,
    Budget,
    Category,
    FinancialAccount,
    Transaction,
    TransactionEvent,
    TransactionImport,
)
from app.schemas.common import PAISA

EXPORT_FORMAT = "finance-ai-export/1"
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "'")

TRANSACTION_COLUMNS = (
    "id",
    "account_id",
    "posted_on",
    "occurred_at",
    "amount",
    "direction",
    "transaction_type",
    "category_id",
    "category_source",
    "description",
    "notes",
    "is_excluded",
    "source",
    "external_id",
    "fingerprint",
    "import_id",
    "import_row_number",
    "transfer_group_id",
    "refund_of_id",
    "created_at",
)


def escape_cell(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_START) else value


def unescape_cell(value: str) -> str:
    return value[1:] if value.startswith("'") else value


def _plain(value: Any) -> Any:
    """JSON-ready, deterministic text for every value type we store."""
    if isinstance(value, Decimal):
        return format(value.quantize(PAISA), "f")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date | UUID):
        return str(value)
    return value


def _row(obj: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    return {name: _plain(getattr(obj, name)) for name in columns}


def _json(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _transactions_csv(rows: list[Transaction]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TRANSACTION_COLUMNS)
    for tx in rows:
        cells = []
        for name in TRANSACTION_COLUMNS:
            value = _plain(getattr(tx, name))
            if value is None:
                cells.append("")
            elif isinstance(value, bool):
                cells.append("true" if value else "false")
            elif isinstance(value, str):
                cells.append(escape_cell(value))
            else:
                cells.append(str(value))
        writer.writerow(cells)
    return buffer.getvalue().encode("utf-8")


def build_export(session: Session, user_id: UUID) -> dict[str, bytes]:
    """Every export file by name, manifest included."""

    def owned(model: Any, *order: Any) -> list[Any]:
        return list(session.scalars(select(model).where(model.user_id == user_id).order_by(*order)))

    accounts = owned(FinancialAccount, FinancialAccount.created_at, FinancialAccount.id)
    snapshots = owned(BalanceSnapshot, BalanceSnapshot.as_of, BalanceSnapshot.source)
    categories = owned(Category, Category.kind, Category.name)
    budgets = owned(Budget, Budget.month, Budget.created_at, Budget.id)
    imports = owned(TransactionImport, TransactionImport.created_at, TransactionImport.id)
    transactions = owned(Transaction, Transaction.posted_on, Transaction.created_at, Transaction.id)
    events = owned(TransactionEvent, TransactionEvent.seq)

    account_columns = (
        "id",
        "name",
        "account_type",
        "institution",
        "currency",
        "last4",
        "is_archived",
        "created_at",
    )
    snapshot_columns = ("id", "account_id", "import_id", "as_of", "balance", "source", "created_at")
    files: dict[str, bytes] = {
        "accounts.json": _json(
            [
                {
                    **_row(a, account_columns),
                    "balance_snapshots": [
                        _row(s, snapshot_columns) for s in snapshots if s.account_id == a.id
                    ],
                }
                for a in accounts
            ]
        ),
        "categories.json": _json(
            [_row(c, ("id", "name", "kind", "is_archived", "created_at")) for c in categories]
        ),
        "budgets.json": _json(
            [
                _row(
                    b,
                    (
                        "id",
                        "category_id",
                        "month",
                        "amount",
                        "warn_at_percent",
                        "created_at",
                        "updated_at",
                    ),
                )
                for b in budgets
            ]
        ),
        "goals.json": _json(_goals(session, user_id)),
        "imports.json": _json(
            [
                _row(
                    i,
                    (
                        "id",
                        "account_id",
                        "source",
                        "profile_id",
                        "file_sha256",
                        "file_size_bytes",
                        "status",
                        "rows_total",
                        "rows_imported",
                        "rows_skipped",
                        "rows_failed",
                        "date_from",
                        "date_to",
                        "closing_balance",
                        "closing_balance_on",
                        "warnings",
                        "error_message",
                        "created_at",
                        "completed_at",
                    ),
                )
                for i in imports
            ]
        ),
        "transaction_events.json": _json(
            [
                _row(
                    e,
                    (
                        "id",
                        "transaction_id",
                        "event_type",
                        "before",
                        "after",
                        "actor",
                        "reason",
                        "created_at",
                    ),
                )
                for e in events
            ]
        ),
        "transactions.csv": _transactions_csv(transactions),
    }
    counts = {
        "accounts.json": len(accounts),
        "categories.json": len(categories),
        "budgets.json": len(budgets),
        "goals.json": len(json.loads(files["goals.json"])),
        "imports.json": len(imports),
        "transaction_events.json": len(events),
        "transactions.csv": len(transactions),
    }
    files["manifest.json"] = _json(
        {
            "format": EXPORT_FORMAT,
            "balance_snapshots": len(snapshots),
            "files": {
                name: {"rows": counts[name], "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in sorted(files.items())
            },
        }
    )
    return files


def _goals(session: Session, user_id: UUID) -> list[dict[str, Any]]:
    """Goals arrive in M8; until then the file is an empty list."""
    return []


def to_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    # A fixed timestamp keeps the zip itself byte-identical for identical data.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    return buffer.getvalue()


def read_transactions_csv(data: bytes) -> list[dict[str, str | None]]:
    """Parse ``transactions.csv`` back, undoing the formula escaping. Empty cell = None."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    return [
        {key: (unescape_cell(value) if value else None) for key, value in row.items()}
        for row in reader
    ]
