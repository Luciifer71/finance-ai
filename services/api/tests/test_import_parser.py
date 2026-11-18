"""The pure CSV parser (handoff 8.1-8.3), using the synthetic fixtures."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.importers.parser import ImportFileError, chronological, parse_statement
from app.importers.profiles import GENERIC_INDIAN_BANK_V1, PROFILES, SIMPLE_V1

FIXTURES = Path(__file__).parent / "fixtures" / "statements"
D = Decimal


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def parse(name_or_bytes: str | bytes, profile=GENERIC_INDIAN_BANK_V1, max_rows: int = 20_000):
    data = load(name_or_bytes) if isinstance(name_or_bytes, str) else name_or_bytes
    return parse_statement(data, profile, max_rows=max_rows)


def test_clean_statement_parses_every_row():
    statement = parse("clean_12_rows.csv")

    assert statement.header_row_number == 1
    assert [r.status for r in statement.rows] == ["valid"] * 12
    first, second = statement.rows[0], statement.rows[1]
    assert (first.posted_on, first.amount, first.direction) == (
        date(2026, 10, 1),
        D("60000.00"),
        "credit",
    )
    assert first.reference is None  # "0000000000" is a placeholder
    assert (second.amount, second.direction, second.reference) == (
        D("450.00"),
        "debit",
        "402711112222",
    )
    assert (statement.closing_balance, statement.closing_balance_on) == (
        D("34125.00"),
        date(2026, 10, 28),
    )
    assert statement.warnings == []  # balances chain: 10000.00 + net 24125.00 = 34125.00


def test_preamble_opening_balance_row_and_summary_footer_are_skipped():
    statement = parse("preamble_footer.csv")

    assert statement.header_row_number == 7
    assert [r.row_number for r in statement.rows] == [9, 10, 11]
    assert statement.ignored_rows == 2  # OPENING BALANCE row and the blank line
    assert statement.rows[2].amount == D("1500.00")  # "1,500.00" in quotes
    # 4980.00 -> 4960.00 -> 6460.00 chains; closing is the last row's balance
    assert statement.closing_balance == D("6460.00")
    assert statement.warnings == []


def test_malformed_rows_are_reported_with_codes_and_row_numbers():
    statement = parse("malformed.csv")
    by_row = {r.row_number: (r.status, r.error_code) for r in statement.rows}

    assert by_row == {
        2: ("valid", None),
        3: ("invalid", "import.row.bad_date"),  # 31 Feb
        4: ("invalid", "import.row.two_amounts"),
        5: ("invalid", "import.row.no_amount"),
        6: ("invalid", "import.row.bad_amount"),
        7: ("valid", None),
    }
    assert all(r.error_message for r in statement.rows if r.status == "invalid")
    assert statement.closing_balance is None  # no balance column values


def test_identical_same_day_rows_are_all_kept_and_rupee_amounts_parse():
    statement = parse("same_day_identical.csv", SIMPLE_V1)
    assert [r.status for r in statement.rows] == ["valid"] * 4
    assert [r.amount for r in statement.rows] == [D("20.00")] * 3 + [D("1200.00")]
    assert statement.rows[3].direction == "credit"


def test_identical_rows_with_the_same_reference_are_one_transaction_printed_twice():
    data = (
        b"date,description,amount,reference\n"
        b"2026-11-05,UPI/X,-20.00,4027000011\n"
        b"2026-11-05,UPI/X,-20.00,4027000011\n"
        b"2026-11-05,UPI/X,-20.00,4027000022\n"
    )
    statuses = [r.status for r in parse(data, SIMPLE_V1).rows]
    assert statuses == ["valid", "duplicate_in_file", "valid"]


def test_cp1252_file_is_decoded():
    statement = parse("cp1252_text.csv", SIMPLE_V1)
    assert statement.rows[0].description == "Café Mocha – Rs. paid"
    assert statement.rows[1].description == "Résumé print"


def test_utf8_bom_is_accepted():
    data = "﻿date,description,amount\n2026-11-05,₹ tea,-20.00\n".encode()
    assert parse(data, SIMPLE_V1).rows[0].description == "₹ tea"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "import.empty_file"),
        (b"   \n\n", "import.empty_file"),
        (b"date,description,amount\n2026-11-05,\x00\x01,-1\n", "import.binary_file"),
        (b"\x81\x8d\x8f\x90\x9d", "import.undecodable"),
        (b"just,some,words\n1,2,3\n", "import.no_header"),
        (b"date,description,amount\n", "import.no_rows"),
        (b'date,description,amount\n2026-11-05,"unterminated,-1\n', "import.malformed_csv"),
    ],
)
def test_file_level_rejections(data: bytes, code: str):
    with pytest.raises(ImportFileError) as excinfo:
        parse(data, SIMPLE_V1)
    assert excinfo.value.code == code


def test_header_must_appear_in_the_first_30_lines():
    late = b"x\n" * 30 + b"date,description,amount\n2026-11-05,a,-1\n"
    with pytest.raises(ImportFileError, match="no_header"):
        parse(late, SIMPLE_V1)
    on_time = b"x\n" * 29 + b"date,description,amount\n2026-11-05,a,-1\n"
    assert len(parse(on_time, SIMPLE_V1).rows) == 1


def test_row_limit():
    rows = "".join(f"2026-11-05,row {i},-1.00\n" for i in range(11))
    data = ("date,description,amount\n" + rows).encode()
    with pytest.raises(ImportFileError) as excinfo:
        parse(data, SIMPLE_V1, max_rows=10)
    assert excinfo.value.code == "import.too_many_rows"
    assert len(parse(data, SIMPLE_V1, max_rows=11).rows) == 11


def test_broken_balance_chain_is_a_warning_not_a_change():
    data = (
        b"date,description,amount,balance\n"
        b"2026-11-01,a,-100.00,900.00\n"
        b"2026-11-02,b,-50.00,800.00\n"  # 900 - 50 = 850, not 800
    )
    statement = parse(data, SIMPLE_V1)
    assert [w["code"] for w in statement.warnings] == ["import.balance_chain_broken"]
    assert statement.warnings[0]["row_number"] == 3
    assert statement.closing_balance == D("800.00")  # reported as printed, never "fixed"


def test_newest_first_statements_are_read_in_date_order():
    data = (
        b"date,description,amount,balance\n"
        b"2026-11-03,c,-10.00,970.00\n"
        b"2026-11-02,b,-10.00,980.00\n"
        b"2026-11-01,a,-20.00,990.00\n"
    )
    statement = parse(data, SIMPLE_V1)
    assert statement.warnings == []
    assert (statement.closing_balance, statement.closing_balance_on) == (
        D("970.00"),
        date(2026, 11, 3),
    )
    assert [r.description for r in chronological(statement.rows)] == ["a", "b", "c"]


def test_unreadable_balance_is_a_warning_and_dr_suffix_is_negative():
    data = (
        b"date,description,amount,balance\n"
        b"2026-11-01,a,-100.00,oops\n"
        b"2026-11-02,b,-50.00,150.00 Dr\n"
    )
    statement = parse(data, SIMPLE_V1)
    assert [r.status for r in statement.rows] == ["valid", "valid"]
    assert statement.rows[1].closing_balance == D("-150.00")
    assert statement.warnings[0]["code"] == "import.row.bad_balance"


def test_zero_and_negative_split_amounts():
    header = b"Date,Narration,Withdrawal Amt.,Deposit Amt.\n"
    zero_other = parse(header + b"01/11/26,a,0.00,500.00\n").rows[0]
    assert (zero_other.amount, zero_other.direction) == (D("500.00"), "credit")
    negative = parse(header + b"01/11/26,a,-5.00,\n").rows[0]
    assert negative.error_code == "import.row.bad_amount"


def test_long_description_is_truncated_and_whitespace_collapsed():
    data = ("date,description,amount\n2026-11-01,  a   b " + "x" * 600 + ",-1\n").encode()
    row = parse(data, SIMPLE_V1).rows[0]
    assert row.description is not None
    assert row.description.startswith("a b x")
    assert len(row.description) == 500


def test_profiles_are_listed_with_verification_labels():
    assert set(PROFILES) == {"generic_indian_bank_v1", "simple_v1"}
    assert GENERIC_INDIAN_BANK_V1.verified is False
    assert "synthetic, not yet verified" in GENERIC_INDIAN_BANK_V1.verification_note
