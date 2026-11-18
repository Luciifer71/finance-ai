"""Balance and verification rules (handoff 6.2). Every expected value is worked out by hand."""

from datetime import date
from decimal import Decimal

from app.domain.balances import (
    DailyMovement,
    Snapshot,
    compute_balance,
    find_anchor,
    reconcile,
)

D = Decimal


def day(d: int, net: str, count: int = 1) -> DailyMovement:
    return DailyMovement(date(2026, 11, d), D(net), count)


def stmt(d: int, balance: str) -> Snapshot:
    return Snapshot(date(2026, 11, d), D(balance), "statement")


def user(d: int, balance: str) -> Snapshot:
    return Snapshot(date(2026, 11, d), D(balance), "user_entered")


def test_no_anchor_starts_from_zero():
    # 0 + 5000.00 - 1200.50 = 3799.50
    result = compute_balance([], [day(2, "5000.00"), day(3, "-1200.50")], date(2026, 11, 30))
    assert result.amount == D("3799.50")
    assert (result.status, result.reason) == ("estimated", "no_anchor")
    assert result.anchor is None
    assert result.transactions_since_anchor == 2


def test_opening_balance_only():
    # opening 10000.00 on 1 Nov, no transactions -> 10000.00, estimated (no statement)
    result = compute_balance([user(1, "10000.00")], [], date(2026, 11, 30))
    assert result.amount == D("10000.00")
    assert (result.status, result.reason) == ("estimated", "no_statement")


def test_opening_balance_plus_later_transactions():
    # 10000.00 - 250.00 (2 Nov) + 1000.00 (3 Nov) = 10750.00
    # the -99.00 on 1 Nov is on the anchor date, already inside the opening balance
    result = compute_balance(
        [user(1, "10000.00")],
        [day(1, "-99.00"), day(2, "-250.00"), day(3, "1000.00")],
        date(2026, 11, 30),
    )
    assert result.amount == D("10750.00")
    assert result.transactions_since_anchor == 2


def test_statement_with_no_later_rows_is_verified():
    result = compute_balance([stmt(15, "4321.09")], [day(14, "-10.00")], date(2026, 11, 18))
    assert result.amount == D("4321.09")
    assert (result.status, result.reason) == ("verified", None)
    assert result.verified_as_of == date(2026, 11, 15)


def test_statement_then_later_rows_is_estimated():
    # 4321.09 - 100.00 (16 Nov) = 4221.09
    result = compute_balance([stmt(15, "4321.09")], [day(16, "-100.00")], date(2026, 11, 18))
    assert result.amount == D("4221.09")
    assert (result.status, result.reason) == ("estimated", "transactions_after_statement")
    assert result.verified_as_of is None


def test_balance_on_a_past_date_ignores_later_rows():
    # As of 15 Nov the 16 Nov row has not happened: verified 4321.09.
    result = compute_balance([stmt(15, "4321.09")], [day(16, "-100.00")], date(2026, 11, 15))
    assert result.amount == D("4321.09")
    assert result.status == "verified"


def test_two_statements_that_reconcile():
    # S1 1000.00 (1 Nov); +500.00 (5 Nov) -200.00 (10 Nov) = 1300.00 = S2 (10 Nov)
    snapshots = [stmt(1, "1000.00"), stmt(10, "1300.00")]
    daily = [day(5, "500.00"), day(10, "-200.00")]
    (pair,) = reconcile(snapshots, daily)
    assert (pair.movement, pair.expected, pair.difference) == (D("300.00"), D("1300.00"), D(0))
    result = compute_balance(snapshots, daily, date(2026, 11, 12))
    assert (result.amount, result.status) == (D("1300.00"), "verified")


def test_two_statements_that_do_not_reconcile_report_the_difference():
    # expected 1000.00 + 300.00 = 1300.00, statement says 1250.00: difference -50.00
    snapshots = [stmt(1, "1000.00"), stmt(10, "1250.00")]
    daily = [day(5, "500.00"), day(10, "-200.00")]
    (pair,) = reconcile(snapshots, daily)
    assert pair.difference == D("-50.00")
    assert not pair.reconciles
    result = compute_balance(snapshots, daily, date(2026, 11, 12))
    # The latest statement is still the anchor; it is never "fixed" silently.
    assert result.amount == D("1250.00")
    assert (result.status, result.reason) == ("estimated", "reconciliation_mismatch")


def test_negative_credit_card_balance():
    # Card statement -12000.00 (owed); purchase 2500.00 (debit) then payment 5000.00 (credit):
    # -12000.00 - 2500.00 + 5000.00 = -9500.00
    result = compute_balance(
        [stmt(5, "-12000.00")], [day(6, "-2500.00"), day(8, "5000.00")], date(2026, 11, 9)
    )
    assert result.amount == D("-9500.00")
    assert result.reason == "transactions_after_statement"


def test_statement_wins_over_user_entered_on_same_day():
    snapshots = [user(10, "999.00"), stmt(10, "1000.00")]
    assert find_anchor(snapshots, date(2026, 11, 10)) == stmt(10, "1000.00")
    assert compute_balance(snapshots, [], date(2026, 11, 10)).status == "verified"


def test_later_user_entered_anchor_after_a_statement():
    # Statement 1 Nov, user adjustment 5 Nov: the adjustment is the anchor, estimated.
    result = compute_balance([stmt(1, "100.00"), user(5, "80.00")], [], date(2026, 11, 6))
    assert result.amount == D("80.00")
    assert result.reason == "user_entered_anchor"


def test_snapshot_after_the_date_is_ignored():
    result = compute_balance([stmt(20, "500.00")], [day(2, "50.00")], date(2026, 11, 10))
    assert (result.amount, result.reason) == (D("50.00"), "no_anchor")
