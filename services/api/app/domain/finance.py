from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


class TransactionType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    user_id: UUID
    account_id: UUID
    amount: Decimal
    type: TransactionType
    currency: str = "INR"
    external_id: str | None = None
    source: str = "manual"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Amount must be a Decimal")

        if not self.amount.is_finite():
            raise ValueError("Amount must be finite")

        if self.amount <= 0:
            raise ValueError("Amount must be positive")

        exponent = self.amount.as_tuple().exponent

        if not isinstance(exponent, int) or exponent < -2:
            raise ValueError("INR amounts support at most 2 decimal places")

        if self.currency != "INR":
            raise ValueError("Only INR is currently supported")

        if not isinstance(self.type, TransactionType):
            raise TypeError("Invalid transaction type")


def calculate_net_cashflow(transactions: list[Transaction]) -> Decimal:
    income = sum(
        (tx.amount for tx in transactions if tx.type == TransactionType.INCOME),
        Decimal(0),
    )
    expenses = sum(
        (tx.amount for tx in transactions if tx.type == TransactionType.EXPENSE),
        Decimal(0),
    )
    return income - expenses


def is_duplicate(
    candidate: Transaction,
    existing: list[Transaction],
) -> bool:
    if candidate.external_id is None:
        return False

    return any(
        tx.user_id == candidate.user_id
        and tx.account_id == candidate.account_id
        and tx.source == candidate.source
        and tx.external_id == candidate.external_id
        for tx in existing
    )
