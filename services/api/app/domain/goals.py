"""Goal projections and the "what if I buy this now?" delay (handoff 6.9). Pure functions.

Fixed saving rate projection, given ``monthly_saving > 0``:
    remaining      = max(target - saved, 0)
    months_needed  = ceil(remaining / monthly_saving)
    projected_date = today + months_needed months (same day, clamped to month end)
With a target date:
    months_until_target = whole months from today to the target date, at least 1
    required_monthly    = remaining / months_until_target, rounded UP to the paisa
    on_track            = monthly_saving >= required_monthly
Purchase delay for a goal saving ``rate`` per month:
    delay = ceil((remaining + amount) / rate) - ceil(remaining / rate)
Default monthly saving: median of the last 3 complete months' net cash flow, if at
least 2 complete months exist and the median is positive.
"""

import calendar
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

from app.domain.money import ceil_to_paisa

ZERO = Decimal("0.00")


def add_months(day: date, months: int) -> date:
    """Same day of the month ``months`` later, clamped to the month's last day
    (31 Jan + 1 month = 28 or 29 Feb)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


def whole_months_between(start: date, end: date) -> int:
    """Completed months from ``start`` to ``end`` (negative if ``end`` is earlier)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months > 0 and end.day < start.day:
        months -= 1
    elif months < 0 and end.day > start.day:
        months += 1
    return months


def ceil_div(amount: Decimal, rate: Decimal) -> int:
    return math.ceil(amount / rate)


@dataclass(frozen=True)
class Projection:
    saved: Decimal
    target: Decimal
    remaining: Decimal
    monthly_saving: Decimal
    months_needed: int
    projected_date: date
    target_date: date | None
    months_until_target: int | None
    required_monthly: Decimal | None
    on_track: bool | None
    target_date_passed: bool | None


def project(
    *,
    target: Decimal,
    saved: Decimal,
    monthly_saving: Decimal,
    today: date,
    target_date: date | None,
) -> Projection:
    if monthly_saving <= 0:
        raise ValueError("monthly_saving must be greater than zero")
    remaining = max(target - saved, ZERO)
    months_needed = ceil_div(remaining, monthly_saving)
    months_until = required = on_track = passed = None
    if target_date is not None:
        months_until = max(whole_months_between(today, target_date), 1)
        required = ceil_to_paisa(remaining / months_until)
        on_track = monthly_saving >= required
        passed = target_date < today
    return Projection(
        saved=saved,
        target=target,
        remaining=remaining,
        monthly_saving=monthly_saving,
        months_needed=months_needed,
        projected_date=add_months(today, months_needed),
        target_date=target_date,
        months_until_target=months_until,
        required_monthly=required,
        on_track=on_track,
        target_date_passed=passed,
    )


def purchase_delay(remaining: Decimal, amount: Decimal, rate: Decimal) -> int:
    if rate <= 0:
        raise ValueError("rate must be greater than zero")
    return ceil_div(remaining + amount, rate) - ceil_div(remaining, rate)


def default_monthly_saving(complete_month_cash_flows: list[Decimal]) -> Decimal | None:
    """Median of the last 3 complete months, or None ("insufficient_history")."""
    recent = complete_month_cash_flows[-3:]
    if len(recent) < 2:
        return None
    value = Decimal(median(recent))
    return value if value > 0 else None
