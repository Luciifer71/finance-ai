"""Reporting periods (handoff 5.4): days, ISO weeks (Monday to Sunday), calendar months
and years. Dates are calendar dates (``posted_on``); no time zone conversion happens here.
"""

import calendar
from datetime import date, timedelta
from typing import Literal

Granularity = Literal["day", "week", "month", "year"]


def period_bounds(granularity: Granularity, day: date) -> tuple[date, date]:
    """First and last date (inclusive) of the period that contains ``day``."""
    if granularity == "day":
        return day, day
    if granularity == "week":
        start = day - timedelta(days=day.weekday())  # Monday
        return start, start + timedelta(days=6)
    if granularity == "month":
        return day.replace(day=1), day.replace(day=days_in_month(day))
    return date(day.year, 1, 1), date(day.year, 12, 31)


def next_period_start(granularity: Granularity, start: date) -> date:
    _, end = period_bounds(granularity, start)
    return end + timedelta(days=1)


def buckets(granularity: Granularity, start: date, end: date) -> list[tuple[date, date]]:
    """The periods covering [start, end], each clipped to that range."""
    result = []
    cursor = start
    while cursor <= end:
        _, period_end = period_bounds(granularity, cursor)
        result.append((cursor, min(period_end, end)))
        cursor = period_end + timedelta(days=1)
    return result


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def parse_month(text: str) -> date:
    """ "2026-11" -> date(2026, 11, 1). Raises ValueError for anything else."""
    year, sep, month = text.partition("-")
    if sep != "-" or len(year) != 4 or len(month) != 2 or not (year + month).isdigit():
        raise ValueError("month must look like 2026-11")
    return date(int(year), int(month), 1)


def month_label(first_day: date) -> str:
    return f"{first_day.year:04d}-{first_day.month:02d}"
