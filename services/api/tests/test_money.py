"""Money parsing and formatting (handoff 6.1). Expected values are written by hand."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.money import (
    MoneyFormatError,
    ceil_to_paisa,
    format_money,
    parse_money,
    percent_1dp,
    quantize_money,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,23,456.70", "123456.70"),  # Indian grouping
        ("12,34,56,789.00", "123456789.00"),
        ("1,234", "1234.00"),
        ("123,456.70", "123456.70"),  # Western grouping
        ("1,234,567.89", "1234567.89"),
        ("123456.7", "123456.70"),
        ("₹ 1,200", "1200.00"),
        ("₹1,200.50", "1200.50"),
        ("Rs. 99", "99.00"),
        ("INR 5", "5.00"),
        ("-50.00", "-50.00"),
        ("₹ -50", "-50.00"),
        ("+20", "20.00"),
        ("  0.10 ", "0.10"),
        ("0", "0.00"),
    ],
)
def test_accepted_inputs(text: str, expected: str):
    assert parse_money(text) == Decimal(expected)
    assert format_money(parse_money(text)) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "₹",
        "10.001",  # three decimals
        "1e3",  # scientific notation
        "1E3",
        "NaN",
        "Infinity",
        "-inf",
        "12,34",  # comma in the wrong place
        "1,2345",
        ",100",
        "100,",
        "1,00.5",
        "1.2.3",
        "abc",
        "--5",
        "10 20",
        "$10",
    ],
)
def test_rejected_inputs(text: str):
    with pytest.raises(MoneyFormatError):
        parse_money(text)


def test_non_text_is_rejected():
    with pytest.raises(MoneyFormatError):
        parse_money(12.5)  # type: ignore[arg-type]  # deliberately wrong type


def test_banker_rounding_only_at_boundaries():
    # 2.345 -> 2.34 (4 is even), 2.355 -> 2.36 (6 is even)
    assert quantize_money(Decimal("2.345")) == Decimal("2.34")
    assert quantize_money(Decimal("2.355")) == Decimal("2.36")


def test_ceil_to_paisa_rounds_up():
    # 1000 / 3 = 333.333... -> 333.34
    assert ceil_to_paisa(Decimal(1000) / Decimal(3)) == Decimal("333.34")
    assert ceil_to_paisa(Decimal("10.00")) == Decimal("10.00")


def test_percent_with_one_decimal():
    # 250 / 1000 = 25.0%; 1 / 3 = 33.333...% -> 33.3%
    assert percent_1dp(Decimal(250), Decimal(1000)) == "25.0"
    assert percent_1dp(Decimal(1), Decimal(3)) == "33.3"
    assert percent_1dp(Decimal(5), Decimal(0)) is None


paise = st.integers(min_value=0, max_value=10**15)


@given(paise)
def test_format_then_parse_round_trips(value: int):
    amount = Decimal(value) / 100
    assert parse_money(format_money(amount)) == amount


@given(st.lists(paise, max_size=50))
def test_sums_never_lose_paise(values: list[int]):
    amounts = [parse_money(format_money(Decimal(v) / 100)) for v in values]
    assert sum(amounts, Decimal(0)) * 100 == sum(values)
