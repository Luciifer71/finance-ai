"""Spending and income totals by period and by category (handoff 6.3)."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession
from app.core.clock import Clock
from app.core.dependencies import get_clock
from app.core.errors import ProblemError
from app.domain.money import percent_1dp
from app.domain.periods import Granularity, buckets, period_bounds
from app.domain.reports import PeriodTotals
from app.repositories import reports as repo
from app.schemas.reports import (
    BucketOut,
    CategoriesOut,
    CategorySpendOut,
    SummaryOut,
    TimeseriesOut,
    TotalsOut,
)

router = APIRouter(prefix="/reports", tags=["reports"])
ClockDep = Annotated[Clock, Depends(get_clock)]
MAX_BUCKETS = 400
EMPTY = PeriodTotals(*(Decimal("0.00"),) * 5)


def totals_out(totals: PeriodTotals) -> TotalsOut:
    return TotalsOut(
        gross_spending=totals.gross_spending,
        refunds=totals.refunds,
        net_spending=totals.net_spending,
        income=totals.income,
        net_cash_flow=totals.net_cash_flow,
    )


def _check_range(date_from: date, date_to: date) -> None:
    if date_from > date_to:
        raise ProblemError(
            422, "report.invalid_range", "Invalid date range", "'from' must not be after 'to'."
        )


@router.get("/summary", response_model=SummaryOut)
def summary(
    user: CurrentUser,
    session: DbSession,
    clock: ClockDep,
    period: Granularity = "month",
    on: Annotated[date | None, Query(alias="date", description="Defaults to today")] = None,
) -> SummaryOut:
    start, end = period_bounds(period, on or clock.today())
    totals = repo.period_totals(session, user.id, start, end)
    return SummaryOut(period=period, start=start, end=end, totals=totals_out(totals))


@router.get("/timeseries", response_model=TimeseriesOut)
def timeseries(
    user: CurrentUser,
    session: DbSession,
    granularity: Granularity,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> TimeseriesOut:
    """One bucket per period; the first and last are clipped to the range. Empty periods
    are included with zero totals."""
    _check_range(date_from, date_to)
    periods = buckets(granularity, date_from, date_to)
    if len(periods) > MAX_BUCKETS:
        raise ProblemError(
            422,
            "report.too_many_buckets",
            "Range too long",
            f"At most {MAX_BUCKETS} periods; use a coarser granularity.",
        )
    by_start = repo.bucketed_totals(session, user.id, date_from, date_to, granularity)
    return TimeseriesOut(
        granularity=granularity,
        date_from=date_from,
        date_to=date_to,
        buckets=[
            BucketOut(
                start=start,
                end=end,
                totals=totals_out(by_start.get(period_bounds(granularity, start)[0], EMPTY)),
            )
            for start, end in periods
        ],
    )


@router.get("/categories", response_model=CategoriesOut)
def categories(
    user: CurrentUser,
    session: DbSession,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> CategoriesOut:
    _check_range(date_from, date_to)
    rows = repo.spending_by_category(session, user.id, date_from, date_to)
    total = sum((r.net_spending for r in rows), Decimal("0.00"))
    return CategoriesOut(
        date_from=date_from,
        date_to=date_to,
        total_net_spending=total,
        items=[
            CategorySpendOut(
                category_id=r.category_id,
                name=r.name,
                gross_spending=r.gross_spending,
                refunds=r.refunds,
                net_spending=r.net_spending,
                share_percent=percent_1dp(r.net_spending, total) if total > 0 else None,
            )
            for r in rows
        ],
    )
