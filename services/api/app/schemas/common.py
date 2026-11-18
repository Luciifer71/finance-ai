"""Types shared by every API schema: money as strings, UTC timestamps with ``Z``."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, WithJsonSchema

from app.domain.money import parse_money

PAISA = Decimal("0.01")


def _money_to_str(value: Decimal) -> str:
    return format(value.quantize(PAISA, rounding=ROUND_HALF_EVEN), "f")


def _parse_money_input(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return parse_money(format(value, "f"))
    if isinstance(value, str):
        return parse_money(value)
    # Floats and ints are refused: money must arrive as a string ("1250.50").
    raise ValueError('money must be a string such as "1250.50"')


_MONEY_SCHEMA = {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["1250.50"]}

# Money in responses: always a string with exactly two decimals.
MoneyOut = Annotated[
    Decimal,
    PlainSerializer(_money_to_str, return_type=str),
    WithJsonSchema(_MONEY_SCHEMA, mode="serialization"),
]

# Money in requests: a string; Indian grouping and ₹ are accepted (section 6.1).
MoneyIn = Annotated[
    Decimal,
    BeforeValidator(_parse_money_input),
    WithJsonSchema(
        {"type": "string", "examples": ["1250.50", "1,23,456.70", "₹ 1,200"]},
        mode="validation",
    ),
]


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[
    datetime,
    PlainSerializer(_utc_iso, return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
