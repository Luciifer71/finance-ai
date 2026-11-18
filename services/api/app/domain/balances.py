"""Account balances and whether we can call them "verified" (handoff section 6.2).

Inputs are plain values so this module has no database code:

- ``snapshots``: balances on dates, from a bank statement or typed by the user.
- ``daily``: for each date, the net signed movement of the account's
  transactions (credits minus debits) and how many transactions there were.

Rules:
- The **anchor** for date D is the latest snapshot with ``as_of <= D``; on the
  same date a statement snapshot wins over a user-entered one.
- Balance on D = anchor balance + net movement with ``anchor.as_of < posted_on <= D``.
  (A statement's closing balance already includes everything posted on ``as_of``.)
- No snapshot at all: start from zero and say so (``no_anchor``).
- **Verified** only when the anchor is a statement, nothing was posted after it
  (up to D), and every pair of consecutive statements up to D reconciles.
  Anything else is **estimated**, with the reason.
"""

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

SnapshotSource = Literal["statement", "user_entered"]
BalanceStatus = Literal["verified", "estimated"]
EstimateReason = Literal[
    "no_statement",
    "transactions_after_statement",
    "user_entered_anchor",
    "no_anchor",
    "reconciliation_mismatch",
]

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class Snapshot:
    as_of: date
    balance: Decimal
    source: SnapshotSource


@dataclass(frozen=True, slots=True)
class DailyMovement:
    posted_on: date
    net: Decimal  # credits minus debits on that day
    count: int


@dataclass(frozen=True, slots=True)
class ReconciliationPair:
    start: Snapshot
    end: Snapshot
    movement: Decimal
    expected: Decimal  # start.balance + movement
    difference: Decimal  # end.balance - expected; zero when they reconcile

    @property
    def reconciles(self) -> bool:
        return self.difference == 0


@dataclass(frozen=True, slots=True)
class Balance:
    on: date
    amount: Decimal
    status: BalanceStatus
    reason: EstimateReason | None
    anchor: Snapshot | None
    transactions_since_anchor: int
    verified_as_of: date | None


def _source_rank(source: SnapshotSource) -> int:
    return 1 if source == "statement" else 0


def find_anchor(snapshots: Iterable[Snapshot], on: date) -> Snapshot | None:
    """Latest snapshot on or before ``on``; a statement beats user-entered on the same day."""
    candidates = [s for s in snapshots if s.as_of <= on]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.as_of, _source_rank(s.source)))


def movement_between(daily: Iterable[DailyMovement], after: date | None, upto: date) -> Decimal:
    """Net movement with ``after < posted_on <= upto`` (no lower bound when ``after`` is None)."""
    return sum(
        (d.net for d in daily if (after is None or d.posted_on > after) and d.posted_on <= upto),
        ZERO,
    )


def count_between(daily: Iterable[DailyMovement], after: date | None, upto: date) -> int:
    return sum(
        d.count for d in daily if (after is None or d.posted_on > after) and d.posted_on <= upto
    )


def reconcile(
    snapshots: Iterable[Snapshot], daily: Sequence[DailyMovement], upto: date | None = None
) -> list[ReconciliationPair]:
    """Check every pair of consecutive statement snapshots (S1 < S2) up to ``upto``."""
    statements = sorted(
        (s for s in snapshots if s.source == "statement" and (upto is None or s.as_of <= upto)),
        key=lambda s: s.as_of,
    )
    pairs = []
    for start, end in itertools.pairwise(statements):
        movement = movement_between(daily, start.as_of, end.as_of)
        expected = start.balance + movement
        pairs.append(
            ReconciliationPair(
                start=start,
                end=end,
                movement=movement,
                expected=expected,
                difference=end.balance - expected,
            )
        )
    return pairs


def compute_balance(
    snapshots: Sequence[Snapshot], daily: Sequence[DailyMovement], on: date
) -> Balance:
    anchor = find_anchor(snapshots, on)
    after = anchor.as_of if anchor else None
    amount = (anchor.balance if anchor else ZERO) + movement_between(daily, after, on)
    since = count_between(daily, after, on)

    reason: EstimateReason | None
    if anchor is None:
        reason = "no_anchor"
    elif anchor.source == "user_entered":
        has_statement = any(s.source == "statement" and s.as_of <= on for s in snapshots)
        reason = "user_entered_anchor" if has_statement else "no_statement"
    elif any(not pair.reconciles for pair in reconcile(snapshots, daily, upto=on)):
        reason = "reconciliation_mismatch"
    elif since > 0:
        reason = "transactions_after_statement"
    else:
        reason = None

    return Balance(
        on=on,
        amount=amount,
        status="verified" if reason is None else "estimated",
        reason=reason,
        anchor=anchor,
        transactions_since_anchor=since,
        verified_as_of=anchor.as_of if reason is None and anchor else None,
    )
