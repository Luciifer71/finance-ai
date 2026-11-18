"""Accounts, opening balances, balances and reconciliation."""

from datetime import date
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.clock import Clock
from app.core.dependencies import get_clock
from app.domain.balances import Balance
from app.models import FinancialAccount
from app.repositories import accounts as repo
from app.schemas.accounts import (
    AccountCreate,
    AccountList,
    AccountOut,
    AccountType,
    AccountUpdate,
    AnchorOut,
    BalanceOut,
    OpeningBalanceIn,
    ReconciliationOut,
    ReconciliationPairOut,
)
from app.services import accounts as service

router = APIRouter(prefix="/accounts", tags=["accounts"])
ClockDep = Annotated[Clock, Depends(get_clock)]


def balance_out(balance: Balance) -> BalanceOut:
    anchor = balance.anchor
    return BalanceOut(
        as_of=balance.on,
        balance=balance.amount,
        status=balance.status,
        reason=balance.reason,
        verified_as_of=balance.verified_as_of,
        anchor=AnchorOut(as_of=anchor.as_of, balance=anchor.balance, source=anchor.source)
        if anchor
        else None,
        transactions_since_anchor=balance.transactions_since_anchor,
    )


def account_out(account: FinancialAccount, balance: Balance) -> AccountOut:
    return AccountOut(
        id=account.id,
        name=account.name,
        # The database's check constraint guarantees one of the AccountType values.
        account_type=cast(AccountType, account.account_type),
        institution=account.institution,
        currency=account.currency,
        last4=account.last4,
        is_archived=account.is_archived,
        created_at=account.created_at,
        balance=balance_out(balance),
    )


@router.get("", response_model=AccountList)
def list_accounts(
    user: CurrentUser,
    session: DbSession,
    clock: ClockDep,
    include_archived: bool = False,
) -> AccountList:
    today = clock.today()
    accounts = repo.list_accounts(session, user.id, include_archived=include_archived)
    return AccountList(
        items=[account_out(a, service.balance_of(session, user.id, a, today)) for a in accounts]
    )


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountCreate, user: CurrentUser, session: DbSession, clock: ClockDep
) -> AccountOut:
    account = service.create_account(session, user.id, body)
    return account_out(account, service.balance_of(session, user.id, account, clock.today()))


@router.get("/{account_id}", response_model=AccountOut)
def read_account(
    account_id: UUID, user: CurrentUser, session: DbSession, clock: ClockDep
) -> AccountOut:
    account = service.get_account(session, user.id, account_id)
    return account_out(account, service.balance_of(session, user.id, account, clock.today()))


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: UUID, body: AccountUpdate, user: CurrentUser, session: DbSession, clock: ClockDep
) -> AccountOut:
    account = service.update_account(session, user.id, account_id, body)
    return account_out(account, service.balance_of(session, user.id, account, clock.today()))


@router.post("/{account_id}/opening-balance", response_model=BalanceOut)
def set_opening_balance(
    account_id: UUID, body: OpeningBalanceIn, user: CurrentUser, session: DbSession
) -> BalanceOut:
    """Record the balance on a date as typed by the user (always shown as an estimate)."""
    service.set_opening_balance(session, user.id, account_id, body)
    account = service.get_account(session, user.id, account_id)
    return balance_out(service.balance_of(session, user.id, account, body.as_of))


@router.get("/{account_id}/balance", response_model=BalanceOut)
def read_balance(
    account_id: UUID,
    user: CurrentUser,
    session: DbSession,
    clock: ClockDep,
    as_of: Annotated[date | None, Query(description="Defaults to today (India time)")] = None,
) -> BalanceOut:
    account = service.get_account(session, user.id, account_id)
    return balance_out(service.balance_of(session, user.id, account, as_of or clock.today()))


@router.get("/{account_id}/reconciliation", response_model=ReconciliationOut)
def read_reconciliation(
    account_id: UUID, user: CurrentUser, session: DbSession
) -> ReconciliationOut:
    pairs = service.reconciliation(session, user.id, account_id)
    overall: Literal["ok", "mismatch", "not_enough_statements"]
    if not pairs:
        overall = "not_enough_statements"
    elif all(p.reconciles for p in pairs):
        overall = "ok"
    else:
        overall = "mismatch"
    return ReconciliationOut(
        account_id=account_id,
        status=overall,
        pairs=[
            ReconciliationPairOut(
                start_as_of=p.start.as_of,
                start_balance=p.start.balance,
                end_as_of=p.end.as_of,
                end_balance=p.end.balance,
                movement=p.movement,
                expected_end_balance=p.expected,
                difference=p.difference,
                reconciles=p.reconciles,
            )
            for p in pairs
        ],
    )
