"""What counts as spending and income (handoff section 6.3), as pure functions.

The API computes these totals in SQL for speed (``repositories/reports.py``);
this module is the readable definition, and tests check the two agree.

For a period [start, end] by ``posted_on`` (inclusive):
- gross_spending = sum of expenses
- refunds = sum of refunds (counted in the period of the refund's own date)
- net_spending = gross_spending - refunds (may be negative)
- income = sum of income
- net_cash_flow = income + refunds - gross_spending
- transfers between the user's own accounts are excluded from all of these
- excluded transactions are left out of every report
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.defaults import UNCATEGORIZED

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    amount: Decimal
    transaction_type: str  # income | expense | transfer | refund
    posted_on: date
    category: str | None = None
    # For a refund linked to its original purchase: the original's category.
    original_category: str | None = None
    refund_linked: bool = False
    is_excluded: bool = False


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    gross_spending: Decimal
    refunds: Decimal
    net_spending: Decimal
    income: Decimal
    net_cash_flow: Decimal


def _in_period(entries: Iterable[LedgerEntry], start: date, end: date) -> list[LedgerEntry]:
    return [e for e in entries if not e.is_excluded and start <= e.posted_on <= end]


def period_totals(entries: Iterable[LedgerEntry], start: date, end: date) -> PeriodTotals:
    rows = _in_period(entries, start, end)

    def total(kind: str) -> Decimal:
        return sum((e.amount for e in rows if e.transaction_type == kind), ZERO)

    gross, refunds, income = total("expense"), total("refund"), total("income")
    return PeriodTotals(
        gross_spending=gross,
        refunds=refunds,
        net_spending=gross - refunds,
        income=income,
        net_cash_flow=income + refunds - gross,
    )


def spending_by_category(
    entries: Iterable[LedgerEntry], start: date, end: date
) -> dict[str, Decimal]:
    """Net spending per category. A linked refund reduces the original purchase's
    category; an unlinked refund reduces its own category (or Uncategorized)."""
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for e in _in_period(entries, start, end):
        if e.transaction_type == "expense":
            totals[e.category or UNCATEGORIZED] += e.amount
        elif e.transaction_type == "refund":
            target = e.original_category if e.refund_linked else e.category
            totals[target or UNCATEGORIZED] -= e.amount
    return dict(totals)
