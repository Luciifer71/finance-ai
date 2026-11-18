"""Section 6.9 math. Every expected value is worked out by hand in the comments."""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.goals import (
    add_months,
    default_monthly_saving,
    project,
    purchase_delay,
    whole_months_between,
)

D = Decimal
TODAY = date(2026, 11, 18)


def test_exact_multiple():
    # remaining 60000 - 0 = 60000; 60000 / 10000 = 6 months exactly -> 18 May 2027
    p = project(
        target=D("60000.00"),
        saved=D("0.00"),
        monthly_saving=D("10000.00"),
        today=TODAY,
        target_date=None,
    )
    assert (p.remaining, p.months_needed, p.projected_date) == (D("60000.00"), 6, date(2027, 5, 18))


def test_remainder_needs_one_more_month():
    # remaining 60000 - 5000 = 55000; 55000 / 10000 = 5.5 -> 6 months -> 18 May 2027
    p = project(
        target=D("60000.00"),
        saved=D("5000.00"),
        monthly_saving=D("10000.00"),
        today=TODAY,
        target_date=None,
    )
    assert (p.remaining, p.months_needed, p.projected_date) == (D("55000.00"), 6, date(2027, 5, 18))
    # remaining 50000.01 / 10000 = 5.000001 -> 6 months
    q = project(
        target=D("50000.01"),
        saved=D("0"),
        monthly_saving=D("10000.00"),
        today=TODAY,
        target_date=None,
    )
    assert q.months_needed == 6


def test_already_achieved():
    p = project(
        target=D("1000.00"),
        saved=D("1200.00"),
        monthly_saving=D("500.00"),
        today=TODAY,
        target_date=date(2027, 1, 1),
    )
    assert (p.remaining, p.months_needed, p.projected_date) == (D("0.00"), 0, TODAY)
    assert (p.required_monthly, p.on_track) == (D("0.00"), True)


def test_target_date_on_and_off_track():
    # remaining 30000; target 18 May 2027 = 6 whole months; required 30000 / 6 = 5000.00
    on = project(
        target=D("30000.00"),
        saved=D("0"),
        monthly_saving=D("5000.00"),
        today=TODAY,
        target_date=date(2027, 5, 18),
    )
    assert (on.months_until_target, on.required_monthly, on.on_track) == (6, D("5000.00"), True)
    # 17 May 2027 is 5 whole months; required 30000 / 5 = 6000.00 > 5000 -> off track
    off = project(
        target=D("30000.00"),
        saved=D("0"),
        monthly_saving=D("5000.00"),
        today=TODAY,
        target_date=date(2027, 5, 17),
    )
    assert (off.months_until_target, off.required_monthly, off.on_track) == (5, D("6000.00"), False)


def test_required_monthly_rounds_up_to_the_paisa():
    # 10000 / 3 = 3333.333... -> 3333.34 (rounding down would leave the goal 0.01 short)
    p = project(
        target=D("10000.00"),
        saved=D("0"),
        monthly_saving=D("3333.33"),
        today=TODAY,
        target_date=date(2027, 2, 18),
    )
    assert (p.months_until_target, p.required_monthly, p.on_track) == (3, D("3333.34"), False)


def test_target_date_in_the_past_counts_as_one_month():
    # Past target: months_until_target is at least 1, required = whole remaining
    p = project(
        target=D("8000.00"),
        saved=D("3000.00"),
        monthly_saving=D("1000.00"),
        today=TODAY,
        target_date=date(2026, 10, 1),
    )
    assert (p.months_until_target, p.required_monthly, p.on_track) == (1, D("5000.00"), False)
    assert p.target_date_passed is True


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2027, 1, 31), 1, date(2027, 2, 28)),  # clamped to month end
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2026, 11, 18), 2, date(2027, 1, 18)),  # across the year
        (date(2026, 8, 31), 3, date(2026, 11, 30)),
        (date(2026, 11, 18), 0, date(2026, 11, 18)),
    ],
)
def test_add_months(start: date, months: int, expected: date):
    assert add_months(start, months) == expected


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        (date(2026, 11, 18), date(2027, 5, 18), 6),
        (date(2026, 11, 18), date(2027, 5, 17), 5),
        (date(2026, 11, 18), date(2026, 11, 30), 0),
        (date(2026, 11, 18), date(2026, 10, 1), -1),
    ],
)
def test_whole_months_between(start: date, end: date, months: int):
    assert whole_months_between(start, end) == months


def test_purchase_delay():
    # remaining 20000, rate 5000: 4 months now; +7000 -> 27000 / 5000 = 5.4 -> 6 months; delay 2
    assert purchase_delay(D("20000.00"), D("7000.00"), D("5000.00")) == 2
    # +5000 exactly: 25000 / 5000 = 5 -> delay 1
    assert purchase_delay(D("20000.00"), D("5000.00"), D("5000.00")) == 1
    # already reached (remaining 0): 999 / 5000 -> 1 month; delay 1
    assert purchase_delay(D("0.00"), D("999.00"), D("5000.00")) == 1
    with pytest.raises(ValueError):
        purchase_delay(D("1"), D("1"), D("0"))


def test_default_monthly_saving():
    assert default_monthly_saving([D("1000")]) is None  # only 1 complete month
    # median of the last 3 of [9000, 1000, 4000, 2500] = median(1000, 4000, 2500) = 2500
    assert default_monthly_saving([D("9000"), D("1000"), D("4000"), D("2500")]) == D("2500")
    # 2 months: median is their mean (3000 + 4000) / 2 = 3500
    assert default_monthly_saving([D("3000"), D("4000")]) == D("3500")
    assert default_monthly_saving([D("-500"), D("200"), D("-100")]) is None  # median -100
    with pytest.raises(ValueError):
        project(target=D("1"), saved=D("0"), monthly_saving=D("0"), today=TODAY, target_date=None)
