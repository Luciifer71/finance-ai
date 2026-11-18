from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.domain.balances import BalanceStatus, EstimateReason, SnapshotSource
from app.schemas.common import ApiModel, MoneyIn, MoneyOut, UtcDatetime

AccountType = Literal["bank", "cash", "credit", "wallet"]
AccountName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Institution = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Last4 = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")]


class AccountCreate(ApiModel):
    name: AccountName
    account_type: AccountType
    institution: Institution | None = None
    last4: Last4 | None = Field(default=None, description="Last 4 digits of the account number")


class AccountUpdate(ApiModel):
    """Only the fields sent are changed. Accounts are archived, never deleted."""

    name: AccountName | None = None
    institution: Institution | None = None
    last4: Last4 | None = None
    is_archived: bool | None = None


class AnchorOut(ApiModel):
    as_of: date
    balance: MoneyOut
    source: SnapshotSource


class BalanceOut(ApiModel):
    as_of: date
    balance: MoneyOut
    status: BalanceStatus
    reason: EstimateReason | None = Field(
        description="Why the balance is an estimate; null when verified"
    )
    verified_as_of: date | None
    anchor: AnchorOut | None
    transactions_since_anchor: int


class AccountOut(ApiModel):
    id: UUID
    name: str
    account_type: AccountType
    institution: str | None
    currency: str
    last4: str | None
    is_archived: bool
    created_at: UtcDatetime
    balance: BalanceOut


class AccountList(ApiModel):
    items: list[AccountOut]


class OpeningBalanceIn(ApiModel):
    as_of: date
    balance: MoneyIn = Field(description="May be negative, e.g. a credit card")


class ReconciliationPairOut(ApiModel):
    start_as_of: date
    start_balance: MoneyOut
    end_as_of: date
    end_balance: MoneyOut
    movement: MoneyOut
    expected_end_balance: MoneyOut
    difference: MoneyOut
    reconciles: bool


class ReconciliationOut(ApiModel):
    account_id: UUID
    status: Literal["ok", "mismatch", "not_enough_statements"]
    pairs: list[ReconciliationPairOut]
