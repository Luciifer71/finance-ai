"""Section 6.3 definitions. Expected values are worked out by hand in the comments."""

from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.reports import LedgerEntry, period_totals, spending_by_category

D = Decimal
NOV1, NOV30 = date(2026, 11, 1), date(2026, 11, 30)


def e(amount: str, kind: str, day: int = 10, month: int = 11, **kw: Any) -> LedgerEntry:
    return LedgerEntry(D(amount), kind, date(2026, month, day), **kw)


def test_transfers_do_not_inflate_spending_or_income():
    # Moving 5000.00 from savings to a wallet is two transfer rows, neither is spending.
    entries = [
        e("5000.00", "transfer"),  # debit side
        e("5000.00", "transfer"),  # credit side
        e("200.00", "expense", category="Food & Dining"),
    ]
    totals = period_totals(entries, NOV1, NOV30)
    assert totals.gross_spending == D("200.00")
    assert totals.income == D("0.00")
    assert totals.net_cash_flow == D("-200.00")
    assert spending_by_category(entries, NOV1, NOV30) == {"Food & Dining": D("200.00")}


def test_period_totals_follow_section_6_3():
    entries = [
        e("60000.00", "income"),
        e("1500.00", "expense", category="Shopping"),
        e("800.00", "expense"),  # uncategorized
        e("500.00", "refund", refund_linked=True, original_category="Shopping"),
        e("99.00", "expense", day=1, month=12),  # outside the period
        e("1000.00", "expense", is_excluded=True),  # excluded from reports
    ]
    totals = period_totals(entries, NOV1, NOV30)
    # gross 1500 + 800 = 2300.00; refunds 500.00; net 1800.00;
    # cash flow 60000 + 500 - 2300 = 58200.00
    assert totals.gross_spending == D("2300.00")
    assert totals.refunds == D("500.00")
    assert totals.net_spending == D("1800.00")
    assert totals.income == D("60000.00")
    assert totals.net_cash_flow == D("58200.00")
    assert spending_by_category(entries, NOV1, NOV30) == {
        "Shopping": D("1000.00"),  # 1500 - 500
        "Uncategorized": D("800.00"),
    }


def test_refund_counts_in_its_own_period_and_can_make_net_negative():
    # Purchase in October, refund in November: November net spending is -700.00.
    entries = [
        e("700.00", "expense", day=25, month=10, category="Shopping"),
        e("700.00", "refund", day=2, refund_linked=True, original_category="Shopping"),
    ]
    totals = period_totals(entries, NOV1, NOV30)
    assert totals.net_spending == D("-700.00")
    assert spending_by_category(entries, NOV1, NOV30) == {"Shopping": D("-700.00")}


def test_unlinked_refund_reduces_its_own_category_or_uncategorized():
    entries = [
        e("300.00", "refund", category="Travel"),
        e("50.00", "refund"),
    ]
    assert spending_by_category(entries, NOV1, NOV30) == {
        "Travel": D("-300.00"),
        "Uncategorized": D("-50.00"),
    }
