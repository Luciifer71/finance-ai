"""User-scoped queries for accounts and their balance inputs."""

from datetime import date
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.domain.balances import DailyMovement, Snapshot
from app.models import BalanceSnapshot, FinancialAccount, Transaction

SIGNED_AMOUNT = case(
    (Transaction.direction == "credit", Transaction.amount), else_=-Transaction.amount
)


def list_accounts(
    session: Session, user_id: UUID, *, include_archived: bool
) -> list[FinancialAccount]:
    statement = select(FinancialAccount).where(FinancialAccount.user_id == user_id)
    if not include_archived:
        statement = statement.where(FinancialAccount.is_archived.is_(False))
    return list(
        session.scalars(statement.order_by(FinancialAccount.created_at, FinancialAccount.id))
    )


def snapshots_for(session: Session, user_id: UUID, account_id: UUID) -> list[Snapshot]:
    rows = session.execute(
        select(BalanceSnapshot.as_of, BalanceSnapshot.balance, BalanceSnapshot.source).where(
            BalanceSnapshot.user_id == user_id, BalanceSnapshot.account_id == account_id
        )
    ).all()
    return [Snapshot(as_of=r.as_of, balance=r.balance, source=r.source) for r in rows]


def daily_movements(
    session: Session, user_id: UUID, account_id: UUID, *, upto: date | None = None
) -> list[DailyMovement]:
    """Net signed movement per posting date. Excluded transactions still count:
    exclusion hides a row from reports, but the money really moved."""
    statement = (
        select(
            Transaction.posted_on,
            func.sum(SIGNED_AMOUNT).label("net"),
            func.count().label("n"),
        )
        .where(Transaction.user_id == user_id, Transaction.account_id == account_id)
        .group_by(Transaction.posted_on)
        .order_by(Transaction.posted_on)
    )
    if upto is not None:
        statement = statement.where(Transaction.posted_on <= upto)
    return [
        DailyMovement(posted_on=r.posted_on, net=r.net, count=r.n)
        for r in session.execute(statement).all()
    ]


def get_user_snapshot(
    session: Session, user_id: UUID, account_id: UUID, as_of: date, source: str
) -> BalanceSnapshot | None:
    return session.scalars(
        select(BalanceSnapshot).where(
            BalanceSnapshot.user_id == user_id,
            BalanceSnapshot.account_id == account_id,
            BalanceSnapshot.as_of == as_of,
            BalanceSnapshot.source == source,
        )
    ).first()
