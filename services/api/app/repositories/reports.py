"""Report aggregations in SQL (definitions: handoff 6.3 and ``app/domain/reports.py``).

Every query: one user, ``posted_on`` between two dates inclusive, excluded rows
left out, transfers never counted.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Date, case, cast, func, select
from sqlalchemy.orm import Session, aliased

from app.domain.periods import Granularity
from app.domain.reports import PeriodTotals
from app.models import Category, Transaction

ZERO = Decimal("0.00")


def _sum_of(kind: str) -> ColumnElement[Decimal]:
    return func.coalesce(
        func.sum(case((Transaction.transaction_type == kind, Transaction.amount), else_=0)), 0
    )


def _in_period(user_id: UUID, start: date, end: date) -> list[ColumnElement[bool]]:
    return [
        Transaction.user_id == user_id,
        Transaction.posted_on >= start,
        Transaction.posted_on <= end,
        Transaction.is_excluded.is_(False),
    ]


def _totals(gross: Decimal, refunds: Decimal, income: Decimal) -> PeriodTotals:
    gross, refunds, income = Decimal(gross), Decimal(refunds), Decimal(income)
    return PeriodTotals(
        gross_spending=gross,
        refunds=refunds,
        net_spending=gross - refunds,
        income=income,
        net_cash_flow=income + refunds - gross,
    )


def period_totals(session: Session, user_id: UUID, start: date, end: date) -> PeriodTotals:
    row = session.execute(
        select(
            _sum_of("expense").label("gross"),
            _sum_of("refund").label("refunds"),
            _sum_of("income").label("income"),
            func.count().filter(Transaction.transaction_type != "transfer").label("n"),
        ).where(*_in_period(user_id, start, end))
    ).one()
    return _totals(row.gross, row.refunds, row.income)


def bucketed_totals(
    session: Session, user_id: UUID, start: date, end: date, granularity: Granularity
) -> dict[date, PeriodTotals]:
    """Totals per period start (``date_trunc``; PostgreSQL weeks start on Monday, ISO)."""
    bucket = cast(func.date_trunc(granularity, Transaction.posted_on), Date).label("bucket")
    rows = session.execute(
        select(
            bucket,
            _sum_of("expense").label("gross"),
            _sum_of("refund").label("refunds"),
            _sum_of("income").label("income"),
        )
        .where(*_in_period(user_id, start, end))
        .group_by(bucket)
    ).all()
    return {row.bucket: _totals(row.gross, row.refunds, row.income) for row in rows}


@dataclass(frozen=True)
class CategoryRow:
    category_id: UUID | None
    name: str
    gross_spending: Decimal
    refunds: Decimal

    @property
    def net_spending(self) -> Decimal:
        return self.gross_spending - self.refunds


def spending_by_category(
    session: Session, user_id: UUID, start: date, end: date
) -> list[CategoryRow]:
    """Net spending per category. A linked refund reduces the original purchase's category;
    an unlinked refund its own. No category means Uncategorized."""
    expenses = session.execute(
        select(Transaction.category_id, func.sum(Transaction.amount))
        .where(*_in_period(user_id, start, end), Transaction.transaction_type == "expense")
        .group_by(Transaction.category_id)
    ).all()
    original = aliased(Transaction)
    refund_category = case(
        (Transaction.refund_of_id.is_not(None), original.category_id),
        else_=Transaction.category_id,
    ).label("category_id")
    refunds = session.execute(
        select(refund_category, func.sum(Transaction.amount))
        .outerjoin(
            original,
            (original.id == Transaction.refund_of_id) & (original.user_id == Transaction.user_id),
        )
        .where(*_in_period(user_id, start, end), Transaction.transaction_type == "refund")
        .group_by(refund_category)
    ).all()
    return _merge_categories(
        session,
        user_id,
        [(row[0], row[1]) for row in expenses],
        [(row[0], row[1]) for row in refunds],
    )


def _merge_categories(
    session: Session,
    user_id: UUID,
    expenses: Sequence[tuple[UUID | None, Decimal]],
    refunds: Sequence[tuple[UUID | None, Decimal]],
) -> list[CategoryRow]:
    names: dict[UUID, str] = {
        row.id: row.name
        for row in session.execute(
            select(Category.id, Category.name).where(Category.user_id == user_id)
        )
    }
    uncategorized = next((cid for cid, name in names.items() if name == "Uncategorized"), None)

    def key(category_id: UUID | None) -> UUID | None:
        return category_id if category_id is not None else uncategorized

    gross: dict[UUID | None, Decimal] = {}
    back: dict[UUID | None, Decimal] = {}
    for category_id, amount in expenses:
        gross[key(category_id)] = gross.get(key(category_id), ZERO) + Decimal(amount)
    for category_id, amount in refunds:
        back[key(category_id)] = back.get(key(category_id), ZERO) + Decimal(amount)
    rows = [
        CategoryRow(
            category_id=category_id,
            name=names.get(category_id, "Uncategorized") if category_id else "Uncategorized",
            gross_spending=gross.get(category_id, ZERO),
            refunds=back.get(category_id, ZERO),
        )
        for category_id in set(gross) | set(back)
    ]
    return sorted(rows, key=lambda r: (-r.net_spending, r.name))
