from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.periods import Granularity
from app.schemas.common import ApiModel, MoneyOut


class TotalsOut(ApiModel):
    """Section 6.3: transfers are never included; excluded rows are left out."""

    gross_spending: MoneyOut
    refunds: MoneyOut
    net_spending: MoneyOut = Field(description="gross_spending - refunds; may be negative")
    income: MoneyOut
    net_cash_flow: MoneyOut = Field(description="income + refunds - gross_spending")


class SummaryOut(ApiModel):
    period: Granularity
    start: date
    end: date
    totals: TotalsOut


class BucketOut(ApiModel):
    start: date
    end: date
    totals: TotalsOut


class TimeseriesOut(ApiModel):
    granularity: Granularity
    date_from: date = Field(serialization_alias="from")
    date_to: date = Field(serialization_alias="to")
    buckets: list[BucketOut]


class CategorySpendOut(ApiModel):
    category_id: UUID | None
    name: str
    gross_spending: MoneyOut
    refunds: MoneyOut
    net_spending: MoneyOut
    share_percent: str | None = Field(description="Share of total net spending, 1 decimal")


class CategoriesOut(ApiModel):
    date_from: date = Field(serialization_alias="from")
    date_to: date = Field(serialization_alias="to")
    total_net_spending: MoneyOut
    items: list[CategorySpendOut]


PeriodName = Literal["day", "week", "month", "year"]
