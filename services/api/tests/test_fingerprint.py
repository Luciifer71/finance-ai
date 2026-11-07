from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.fingerprint import (
    StatementRow,
    fingerprint_rows,
    normalize_text,
    transaction_fingerprint,
)

ACCOUNT = uuid4()


def chai(**overrides) -> StatementRow:
    values = {
        "posted_on": date(2026, 11, 5),
        "amount": Decimal("20.00"),
        "direction": "debit",
        "description": "UPI/CHAI POINT",
        "reference": None,
    }
    values.update(overrides)
    return StatementRow(**values)


def test_two_identical_purchases_get_different_fingerprints():
    first, second = fingerprint_rows(ACCOUNT, [chai(), chai()])
    assert first != second


def test_reimporting_the_same_file_gives_the_same_fingerprints():
    statement = [chai(), chai(), chai(amount=Decimal("150.00"))]
    assert fingerprint_rows(ACCOUNT, statement) == fingerprint_rows(ACCOUNT, statement)


def test_overlapping_statements_agree_on_shared_rows():
    # October statement and a mid-Oct to mid-Nov statement both include 5 Nov.
    older = [chai(posted_on=date(2026, 11, 4)), chai(), chai()]
    newer = [chai(), chai(), chai(posted_on=date(2026, 11, 6))]
    assert fingerprint_rows(ACCOUNT, older)[1:] == fingerprint_rows(ACCOUNT, newer)[:2]


def test_cosmetic_differences_are_ignored():
    a = fingerprint_rows(ACCOUNT, [chai(description="UPI/CHAI  POINT ")])
    b = fingerprint_rows(ACCOUNT, [chai(description="upi/chai point")])
    assert a == b


def test_trailing_zeros_in_amount_do_not_matter():
    a = fingerprint_rows(ACCOUNT, [chai(amount=Decimal(20))])
    b = fingerprint_rows(ACCOUNT, [chai(amount=Decimal("20.00"))])
    assert a == b


@pytest.mark.parametrize(
    "change",
    [
        {"posted_on": date(2026, 11, 6)},
        {"amount": Decimal("20.01")},
        {"direction": "credit"},
        {"description": "UPI/COFFEE"},
        {"reference": "UTR123"},
    ],
)
def test_any_real_difference_changes_the_fingerprint(change):
    assert fingerprint_rows(ACCOUNT, [chai()]) != fingerprint_rows(ACCOUNT, [chai(**change)])


def test_same_row_in_different_accounts_is_not_a_duplicate():
    assert fingerprint_rows(uuid4(), [chai()]) != fingerprint_rows(uuid4(), [chai()])


def test_fingerprint_is_64_hex_characters():
    value = transaction_fingerprint(ACCOUNT, chai(), occurrence=1)
    assert len(value) == 64
    int(value, 16)


def test_occurrence_must_start_at_one():
    with pytest.raises(ValueError):
        transaction_fingerprint(ACCOUNT, chai(), occurrence=0)


def test_normalize_text_handles_missing_values():
    assert normalize_text(None) == ""
    assert normalize_text("  Hello   World ") == "hello world"
