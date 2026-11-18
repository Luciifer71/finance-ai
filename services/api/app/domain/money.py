"""Exact money parsing and formatting (handoff section 6.1).

Rules:
- Money is ``Decimal`` with at most 2 decimal places, never a float.
- Accepted input: "1,23,456.70" (Indian grouping), "123,456.70" (Western
  grouping), "123456.7", "₹ 1,200", "Rs. 1,200", "INR 1200", "-50.00".
- Rejected: more than two decimals, scientific notation ("1e3"), NaN/Infinity,
  empty strings, misplaced commas ("12,34", "1,2345"), anything else.
- Rounding (``ROUND_HALF_EVEN``, "banker's rounding") happens only where a
  computed value (an average or projection) is returned, via ``quantize_money``.
"""

import re
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal, InvalidOperation

PAISA = Decimal("0.01")
ZERO = Decimal("0.00")

_CURRENCY_PREFIX = re.compile(r"^(?:₹|rs\.?|inr)\s*", re.IGNORECASE)
_PLAIN = re.compile(r"^\d+(?:\.\d{1,2})?$")
_INDIAN = re.compile(r"^\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d{1,2})?$|^\d{1,3},\d{3}(?:\.\d{1,2})?$")
_WESTERN = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?$")


class MoneyFormatError(ValueError):
    """The text is not a valid INR amount."""


def parse_money(text: str) -> Decimal:
    """Parse user or statement text into an exact Decimal with 2 places."""
    if not isinstance(text, str):
        raise MoneyFormatError("amount must be text")
    value = text.strip()
    sign = ""
    if value[:1] in {"-", "+"}:
        sign, value = value[0], value[1:].strip()
    value = _CURRENCY_PREFIX.sub("", value)
    if value[:1] in {"-", "+"} and not sign:  # "₹ -50"
        sign, value = value[0], value[1:].strip()
    if not value:
        raise MoneyFormatError("amount is empty")
    if not (_PLAIN.match(value) or _INDIAN.match(value) or _WESTERN.match(value)):
        raise MoneyFormatError("amount is not a valid rupee value with at most 2 decimals")
    try:
        amount = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - the regexes already guarantee digits
        raise MoneyFormatError("amount is not a number") from exc
    amount = amount.quantize(PAISA)
    return -amount if sign == "-" else amount


def quantize_money(value: Decimal) -> Decimal:
    """Round a computed value to paise with banker's rounding (only at output boundaries)."""
    return value.quantize(PAISA, rounding=ROUND_HALF_EVEN)


def ceil_to_paisa(value: Decimal) -> Decimal:
    """Round up to the next paisa (used where rounding down would under-save)."""
    return value.quantize(PAISA, rounding=ROUND_CEILING)


def format_money(value: Decimal) -> str:
    """Exactly two decimals, no grouping: ``Decimal("20")`` -> ``"20.00"``."""
    return format(quantize_money(value), "f")


def percent_1dp(numerator: Decimal, denominator: Decimal) -> str | None:
    """``numerator / denominator`` as a percentage string with 1 decimal, or None for /0."""
    if denominator == 0:
        return None
    return format(
        (numerator * 100 / denominator).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN), "f"
    )
