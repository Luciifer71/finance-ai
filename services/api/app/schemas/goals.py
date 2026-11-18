from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, StringConstraints, UrlConstraints, field_validator

from app.schemas.accounts import BalanceOut
from app.schemas.common import ApiModel, MoneyIn, MoneyOut, UtcDatetime

GoalKind = Literal["wishlist", "savings"]
GoalStatus = Literal["active", "achieved", "abandoned"]
GoalName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Priority = Annotated[int, Field(ge=1, le=5, description="1 = most important")]
ItemUrl = Annotated[AnyHttpUrl, UrlConstraints(max_length=2000, allowed_schemes=["http", "https"])]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _positive(value: Decimal | None) -> Decimal | None:
    if value is not None and value <= 0:
        raise ValueError("amount must be greater than zero")
    return value


class GoalCreate(ApiModel):
    name: GoalName
    kind: GoalKind
    target_amount: MoneyIn
    target_date: date | None = None
    item_url: ItemUrl | None = Field(default=None, description="http or https only")
    priority: Priority = 3

    _amount = field_validator("target_amount")(_positive)


class GoalUpdate(ApiModel):
    name: GoalName | None = None
    target_amount: MoneyIn | None = None
    target_date: date | None = None
    item_url: ItemUrl | None = None
    priority: Priority | None = None
    status: GoalStatus | None = None

    _amount = field_validator("target_amount")(_positive)


class GoalEventIn(ApiModel):
    event_type: Literal["contribution", "withdrawal", "note"]
    amount: MoneyIn | None = None
    note: Note | None = None


class GoalEventOut(ApiModel):
    id: UUID
    event_type: str
    amount: MoneyOut | None
    before: dict[str, Any]
    after: dict[str, Any]
    note: str | None
    actor: Literal["user", "system"]
    created_at: UtcDatetime


class GoalOut(ApiModel):
    id: UUID
    name: str
    kind: GoalKind
    target_amount: MoneyOut
    target_date: date | None
    item_url: str | None
    priority: int
    status: GoalStatus
    saved: MoneyOut = Field(description="contributions - withdrawals (earmarked, not moved)")
    remaining: MoneyOut
    created_at: UtcDatetime
    updated_at: UtcDatetime


class GoalDetail(GoalOut):
    events: list[GoalEventOut]


class GoalList(ApiModel):
    items: list[GoalOut]


class GoalProjectionOut(ApiModel):
    status: Literal["ok", "insufficient_history"]
    monthly_saving: MoneyOut | None
    monthly_saving_source: Literal["given", "median_of_recent_months"] | None
    saved: MoneyOut
    target_amount: MoneyOut
    remaining: MoneyOut
    months_needed: int | None
    projected_date: date | None
    target_date: date | None
    months_until_target: int | None
    required_monthly: MoneyOut | None
    on_track: bool | None
    target_date_passed: bool | None
    assumptions: list[str]


class PurchaseIn(ApiModel):
    amount: MoneyIn
    account_id: UUID | None = None
    category_id: UUID | None = Field(default=None, description="To check that category's budget")

    _amount = field_validator("amount")(_positive)


class BudgetImpactOut(ApiModel):
    budget_id: UUID
    category_id: UUID | None
    category_name: str | None
    spent_before: MoneyOut
    spent_after: MoneyOut
    amount: MoneyOut
    status_before: Literal["ok", "warning", "over"]
    status_after: Literal["ok", "warning", "over"]


class GoalImpactOut(ApiModel):
    goal_id: UUID
    name: str
    remaining: MoneyOut
    delay_months: int | None
    reason: Literal["insufficient_history"] | None


class PurchaseOut(ApiModel):
    amount: MoneyOut
    account_id: UUID | None
    balance_before: BalanceOut | None
    balance_after: MoneyOut | None
    month_net_spending_before: MoneyOut
    month_net_spending_after: MoneyOut
    budgets: list[BudgetImpactOut]
    goals: list[GoalImpactOut]
    monthly_saving: MoneyOut | None
    assumptions: list[str]
    written: Literal[False] = Field(default=False, description="Nothing is ever saved")
