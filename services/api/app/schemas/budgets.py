from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from app.schemas.common import ApiModel, MoneyIn, MoneyOut, UtcDatetime

Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
WarnPercent = Annotated[int, Field(ge=1, le=100)]


def _positive(value: Decimal | None) -> Decimal | None:
    if value is not None and value <= 0:
        raise ValueError("amount must be greater than zero")
    return value


class BudgetCreate(ApiModel):
    category_id: UUID | None = Field(default=None, description="null = all spending")
    month: Month = Field(examples=["2026-11"])
    amount: MoneyIn
    warn_at_percent: WarnPercent = 80

    _check_amount = field_validator("amount")(_positive)


class BudgetUpdate(ApiModel):
    amount: MoneyIn | None = None
    warn_at_percent: WarnPercent | None = None

    _check_amount = field_validator("amount")(_positive)


class BudgetOut(ApiModel):
    id: UUID
    category_id: UUID | None
    month: str
    amount: MoneyOut
    warn_at_percent: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class BudgetList(ApiModel):
    items: list[BudgetOut]


class ProjectionOut(ApiModel):
    projected_spending: MoneyOut | None
    may_exceed: bool | None
    reason: Literal["too_early_in_month", "not_current_month"] | None
    days_elapsed: int | None
    days_in_month: int
    formula: str = "spent / days_elapsed * days_in_month"


class BudgetStatusOut(ApiModel):
    budget_id: UUID
    category_id: UUID | None
    category_name: str | None = Field(description="null = all spending")
    amount: MoneyOut
    net_spending: MoneyOut
    spent: MoneyOut = Field(description="net spending floored at 0")
    warn_threshold: MoneyOut
    remaining: MoneyOut
    percent_used: str
    status: Literal["ok", "warning", "over"]
    projection: ProjectionOut


class BudgetStatusList(ApiModel):
    month: str
    items: list[BudgetStatusOut]
