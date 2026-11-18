"""Accounts, opening balances, computed balances and reconciliation."""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.balances import Balance, ReconciliationPair, compute_balance, reconcile
from app.models import BalanceSnapshot, FinancialAccount
from app.repositories import accounts as repo
from app.repositories.common import get_owned_or_404
from app.schemas.accounts import AccountCreate, AccountUpdate, OpeningBalanceIn


def get_account(session: Session, user_id: UUID, account_id: UUID) -> FinancialAccount:
    return get_owned_or_404(session, FinancialAccount, account_id, user_id, "account")


def create_account(session: Session, user_id: UUID, data: AccountCreate) -> FinancialAccount:
    account = FinancialAccount(
        user_id=user_id,
        name=data.name,
        institution=data.institution,
        account_type=data.account_type,
        currency="INR",
        last4=data.last4,
    )
    session.add(account)
    session.commit()
    return account


def update_account(
    session: Session, user_id: UUID, account_id: UUID, data: AccountUpdate
) -> FinancialAccount:
    account = get_owned_or_404(
        session, FinancialAccount, account_id, user_id, "account", for_update=True
    )
    for field in data.model_fields_set:
        value = getattr(data, field)
        if field in {"name", "is_archived"} and value is None:
            continue  # these cannot be cleared
        setattr(account, field, value)
    session.commit()
    return account


def set_opening_balance(
    session: Session, user_id: UUID, account_id: UUID, data: OpeningBalanceIn
) -> BalanceSnapshot:
    """Record a user-entered balance. Entering one again for the same date replaces it.

    This is also how a manual adjustment is made: never by inventing a transaction.
    """
    get_owned_or_404(session, FinancialAccount, account_id, user_id, "account")
    snapshot = repo.get_user_snapshot(session, user_id, account_id, data.as_of, "user_entered")
    if snapshot is None:
        snapshot = BalanceSnapshot(
            user_id=user_id,
            account_id=account_id,
            as_of=data.as_of,
            balance=data.balance,
            source="user_entered",
        )
        session.add(snapshot)
    else:
        snapshot.balance = data.balance
    session.commit()
    return snapshot


def balance_of(session: Session, user_id: UUID, account: FinancialAccount, on: date) -> Balance:
    return compute_balance(
        repo.snapshots_for(session, user_id, account.id),
        repo.daily_movements(session, user_id, account.id, upto=on),
        on,
    )


def reconciliation(session: Session, user_id: UUID, account_id: UUID) -> list[ReconciliationPair]:
    get_owned_or_404(session, FinancialAccount, account_id, user_id, "account")
    return reconcile(
        repo.snapshots_for(session, user_id, account_id),
        repo.daily_movements(session, user_id, account_id),
    )
