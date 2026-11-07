from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.finance import (
    Transaction,
    TransactionType,
    calculate_net_cashflow,
    is_duplicate,
)

USER_ID = uuid4()
ACCOUNT_ID = uuid4()


def make_transaction(
    amount: str,
    kind: TransactionType,
    external_id: str | None = None,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        amount=Decimal(amount),
        type=kind,
        external_id=external_id,
    )


def test_income_increases_cashflow():
    tx = make_transaction("1000.00", TransactionType.INCOME)
    assert calculate_net_cashflow([tx]) == Decimal("1000.00")


def test_expense_decreases_cashflow():
    tx = make_transaction("250.00", TransactionType.EXPENSE)
    assert calculate_net_cashflow([tx]) == Decimal("-250.00")


def test_transfer_does_not_count_as_expense():
    tx = make_transaction("500.00", TransactionType.TRANSFER)
    assert calculate_net_cashflow([tx]) == Decimal(0)


def test_financial_precision():
    transactions = [
        make_transaction("0.10", TransactionType.INCOME),
        make_transaction("0.20", TransactionType.INCOME),
    ]
    assert calculate_net_cashflow(transactions) == Decimal("0.30")


def test_negative_amount_rejected():
    with pytest.raises(ValueError):
        make_transaction("-100.00", TransactionType.EXPENSE)


def test_fractional_paise_rejected():
    with pytest.raises(ValueError):
        make_transaction("10.001", TransactionType.EXPENSE)


def test_duplicate_external_transaction():
    existing = make_transaction("100.00", TransactionType.EXPENSE, "UPI123")
    candidate = make_transaction("100.00", TransactionType.EXPENSE, "UPI123")

    assert is_duplicate(candidate, [existing])


def test_different_external_transactions():
    existing = make_transaction("100.00", TransactionType.EXPENSE, "UPI123")
    candidate = make_transaction("100.00", TransactionType.EXPENSE, "UPI456")

    assert not is_duplicate(candidate, [existing])


def test_refund_gives_spent_money_back():
    transactions = [
        make_transaction("1200.00", TransactionType.EXPENSE),
        make_transaction("1200.00", TransactionType.REFUND),
    ]
    assert calculate_net_cashflow(transactions) == Decimal("0.00")
