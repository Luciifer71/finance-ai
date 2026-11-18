"""Budget status and month-end projection (handoff 6.8). Pure functions.

- ``spent`` = net spending for the budget's category and month, floored at 0
  (refunds can make net spending negative; a budget cannot be "below empty").
- ``warn_threshold`` = amount x warn_at_percent / 100.
- status: ``ok`` below the threshold, ``warning`` from the threshold up to (not
  including) the amount, ``over`` at or above the amount.
- Projection (current month only, from day 7): spent / days_elapsed x days_in_month,
  where days_elapsed includes today. ``may_exceed`` = projected >= amount.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.domain.periods import days_in_month

BudgetStatus = Literal["ok", "warning", "over"]
MIN_DAYS_FOR_PROJECTION = 7
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Projection:
    projected: Decimal | None
    may_exceed: bool | None
    reason: Literal["too_early_in_month", "not_current_month"] | None
    days_elapsed: int | None
    days_in_month: int


@dataclass(frozen=True)
class BudgetEvaluation:
    amount: Decimal
    net_spending: Decimal
    spent: Decimal
    warn_threshold: Decimal
    status: BudgetStatus
    remaining: Decimal
    projection: Projection


def budget_status(amount: Decimal, warn_at_percent: int, spent: Decimal) -> BudgetStatus:
    threshold = amount * warn_at_percent / 100
    if spent >= amount:
        return "over"
    if spent >= threshold:
        return "warning"
    return "ok"


def project_month_end(month: date, today: date, spent: Decimal, amount: Decimal) -> Projection:
    total_days = days_in_month(month)
    if (month.year, month.month) != (today.year, today.month):
        return Projection(None, None, "not_current_month", None, total_days)
    elapsed = today.day  # includes today
    if elapsed < MIN_DAYS_FOR_PROJECTION:
        return Projection(None, None, "too_early_in_month", elapsed, total_days)
    projected = spent / elapsed * total_days
    return Projection(projected, projected >= amount, None, elapsed, total_days)


def evaluate(
    amount: Decimal, warn_at_percent: int, net_spending: Decimal, month: date, today: date
) -> BudgetEvaluation:
    spent = max(net_spending, ZERO)
    return BudgetEvaluation(
        amount=amount,
        net_spending=net_spending,
        spent=spent,
        warn_threshold=amount * warn_at_percent / 100,
        status=budget_status(amount, warn_at_percent, spent),
        remaining=amount - spent,
        projection=project_month_end(month, today, spent, amount),
    )
