from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints

from app.schemas.common import ApiModel, MoneyIn, MoneyOut, UtcDatetime

Direction = Literal["debit", "credit"]
TransactionType = Literal["income", "expense", "transfer", "refund"]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class TransactionOut(ApiModel):
    id: UUID
    account_id: UUID
    import_id: UUID | None
    category_id: UUID | None
    amount: MoneyOut = Field(description="Always positive; the sign is in `direction`")
    signed_amount: MoneyOut = Field(description="+amount for credit, -amount for debit")
    direction: Direction
    transaction_type: TransactionType
    description: str | None
    source: str
    posted_on: date
    occurred_at: UtcDatetime | None
    transfer_group_id: UUID | None
    refund_of_id: UUID | None
    notes: str | None
    category_source: Literal["rule", "user", "system", "none"]
    is_excluded: bool
    created_at: UtcDatetime


class TransactionEventOut(ApiModel):
    id: UUID
    event_type: str
    before: dict[str, Any]
    after: dict[str, Any]
    actor: Literal["user", "system", "rule"]
    reason: str | None
    created_at: UtcDatetime


class TransactionDetail(TransactionOut):
    events: list[TransactionEventOut]


class TransactionEventList(ApiModel):
    items: list[TransactionEventOut]


class TransactionUpdate(ApiModel):
    """Only the fields sent are changed. Amount, date and description can never change."""

    category_id: UUID | None = Field(default=None, description="null = uncategorized")
    notes: Annotated[str, StringConstraints(max_length=1000)] | None = None
    is_excluded: bool | None = Field(default=None, description="Hide from reports")
    transaction_type: Literal["income", "expense", "refund"] | None = None
    create_rule: bool = Field(
        default=False,
        description="Also remember merchant -> category for future imports (needs category_id)",
    )


class TransactionPage(ApiModel):
    items: list[TransactionOut]
    next_cursor: str | None


class ManualTransactionCreate(ApiModel):
    """A transaction typed in by the user, e.g. a cash purchase."""

    account_id: UUID
    posted_on: date
    amount: MoneyIn = Field(description='Positive amount, e.g. "250.00"')
    direction: Direction
    transaction_type: Literal["income", "expense", "refund"] | None = Field(
        default=None,
        description="Defaults to expense for debit and income for credit. "
        "Transfers are created by pairing two transactions.",
    )
    description: Description | None = None
    category_id: UUID | None = None
    occurred_at: AwareDatetime | None = None
