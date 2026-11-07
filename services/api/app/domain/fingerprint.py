"""Stable fingerprints for detecting duplicate imported transactions.

A bank statement row does not always have a reference number (UTR), so we
cannot rely on ``external_id`` alone to spot duplicates. Instead, every row
gets a fingerprint built from the facts the bank printed: date, amount,
direction, reference and description.

Two genuinely different purchases can look identical (two ₹20 chai payments on
the same day with the same description). To keep both, each row also carries
an ``occurrence`` number: 1 for the first identical row in a file, 2 for the
second and so on. Re-importing the same file produces the same occurrence
numbers, so the same fingerprints, so nothing is added twice.
"""

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

Direction = Literal["debit", "credit"]

# Bump this if the recipe below ever changes, so old and new fingerprints
# can never be confused with each other.
FINGERPRINT_VERSION = "v1"


def normalize_text(value: str | None) -> str:
    """Lower-case and collapse whitespace so cosmetic differences don't matter."""
    if value is None:
        return ""
    return " ".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class StatementRow:
    """The bank-provided facts used to identify one statement row."""

    posted_on: date
    amount: Decimal
    direction: Direction
    description: str | None = None
    reference: str | None = None

    def base_key(self) -> tuple[str, ...]:
        """Everything except the occurrence number, normalized."""
        return (
            self.posted_on.isoformat(),
            format(self.amount.quantize(Decimal("0.01")), "f"),
            self.direction,
            normalize_text(self.reference),
            normalize_text(self.description),
        )


def transaction_fingerprint(account_id: UUID, row: StatementRow, occurrence: int) -> str:
    """Return a 64-character hex fingerprint for one row of one account."""
    if occurrence < 1:
        raise ValueError("occurrence starts at 1")

    parts = (FINGERPRINT_VERSION, str(account_id), *row.base_key(), str(occurrence))
    # The unit separator character cannot appear in normal text, so two
    # different sets of parts can never join into the same string.
    payload = "\x1f".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_rows(account_id: UUID, rows: Iterable[StatementRow]) -> list[str]:
    """Fingerprint every row of one statement file, numbering identical rows."""
    seen: Counter[tuple[str, ...]] = Counter()
    fingerprints = []

    for row in rows:
        key = row.base_key()
        seen[key] += 1
        fingerprints.append(transaction_fingerprint(account_id, row, seen[key]))

    return fingerprints
