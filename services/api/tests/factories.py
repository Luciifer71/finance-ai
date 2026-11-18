"""Insert synthetic ledger rows directly, for tests that need a known starting state."""

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import BalanceSnapshot, FinancialAccount, Transaction, TransactionImport


def add_account(
    session: Session, user_id: UUID, name: str = "Synthetic Bank", account_type: str = "bank"
) -> FinancialAccount:
    account = FinancialAccount(
        user_id=user_id, name=name, account_type=account_type, currency="INR"
    )
    session.add(account)
    session.flush()
    return account


def add_tx(
    session: Session,
    user_id: UUID,
    account_id: UUID,
    posted_on: date,
    amount: str,
    direction: str = "debit",
    transaction_type: str | None = None,
    description: str | None = None,
    **extra: object,
) -> Transaction:
    row_id = uuid.uuid4()
    tx = Transaction(
        id=row_id,
        user_id=user_id,
        account_id=account_id,
        amount=Decimal(amount),
        direction=direction,
        transaction_type=transaction_type or ("expense" if direction == "debit" else "income"),
        description=description,
        source="test",
        fingerprint=hashlib.sha256(f"test{row_id}".encode()).hexdigest(),
        posted_on=posted_on,
        **extra,
    )
    session.add(tx)
    session.flush()
    return tx


def add_statement_snapshot(
    session: Session, user_id: UUID, account_id: UUID, as_of: date, balance: str
) -> BalanceSnapshot:
    """A statement closing balance. Statement snapshots must point at an import."""
    statement_import = TransactionImport(
        user_id=user_id,
        account_id=account_id,
        source="test",
        file_sha256=hashlib.sha256(f"{account_id}{as_of}".encode()).hexdigest(),
        status="completed",
    )
    session.add(statement_import)
    session.flush()
    snapshot = BalanceSnapshot(
        user_id=user_id,
        account_id=account_id,
        import_id=statement_import.id,
        as_of=as_of,
        balance=Decimal(balance),
        source="statement",
    )
    session.add(snapshot)
    session.flush()
    return snapshot
