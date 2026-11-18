"""Turn the bytes of a CSV statement into parsed rows (handoff sections 8.1-8.3).

Pure functions: no database, no file system. The service layer adds the
account-specific parts (fingerprints, "already imported").

File-level problems raise ``ImportFileError`` with a stable code. Row-level
problems never stop the import: the row is marked ``invalid`` with a code and
a message the user can act on, and every valid row is still imported.
"""

import csv
import hashlib
import io
import itertools
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from app.domain.fingerprint import StatementRow
from app.domain.money import MoneyFormatError, parse_money
from app.importers.profiles import ImportProfile

HEADER_SEARCH_LINES = 30
MAX_DESCRIPTION = 500
MAX_REFERENCE = 200
MAX_WARNINGS = 20

RowStatus = Literal["valid", "invalid", "duplicate_in_file"]


class ImportFileError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class ParsedRow:
    row_number: int
    raw_hash: str
    status: RowStatus
    posted_on: date | None = None
    value_date: date | None = None
    description: str | None = None
    reference: str | None = None
    amount: Decimal | None = None
    direction: Literal["debit", "credit"] | None = None
    closing_balance: Decimal | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def signed_amount(self) -> Decimal:
        if self.amount is None:
            raise ValueError("only valid rows have an amount")
        return self.amount if self.direction == "credit" else -self.amount

    def statement_row(self) -> StatementRow:
        """The facts that identify this row (fingerprint input)."""
        if self.posted_on is None or self.amount is None or self.direction is None:
            raise ValueError("only valid rows have statement facts")
        return StatementRow(
            posted_on=self.posted_on,
            amount=self.amount,
            direction=self.direction,
            description=self.description,
            reference=self.reference,
        )


@dataclass
class ParsedStatement:
    header_row_number: int
    rows: list[ParsedRow]
    ignored_rows: int
    warnings: list[dict[str, object]] = field(default_factory=list)
    closing_balance: Decimal | None = None
    closing_balance_on: date | None = None

    @property
    def valid_rows(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.status == "valid"]


# --- file level ----------------------------------------------------------------------------


def decode_bytes(data: bytes) -> str:
    """UTF-8 (with or without BOM), else Windows-1252 (what Excel on Windows often writes)."""
    if not data.strip():
        raise ImportFileError(422, "import.empty_file", "The file is empty.")
    if b"\x00" in data:
        raise ImportFileError(422, "import.binary_file", "This does not look like a CSV text file.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise ImportFileError(
            422, "import.undecodable", "The file's text encoding could not be read."
        ) from exc


def _read_csv(text: str) -> list[tuple[int, list[str]]]:
    """(line number, cells) for every record. Line numbers are 1-based."""
    # strict: an unterminated quote is an error, not a silent merge of every later line.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    records: list[tuple[int, list[str]]] = []
    try:
        for cells in reader:
            records.append((reader.line_num, cells))
    except csv.Error as exc:
        raise ImportFileError(
            422, "import.malformed_csv", "The file is not valid CSV (check quotes)."
        ) from exc
    return records


def _find_header(
    records: list[tuple[int, list[str]]], profile: ImportProfile
) -> tuple[int, dict[str, int]]:
    for index, (_line, cells) in enumerate(records[:HEADER_SEARCH_LINES]):
        mapping = profile.match_header(cells)
        if mapping is not None:
            return index, mapping
    raise ImportFileError(
        422,
        "import.no_header",
        f"No header row for '{profile.label}' was found in the first "
        f"{HEADER_SEARCH_LINES} lines. Check the profile, or that the file is a statement.",
    )


# --- row level -----------------------------------------------------------------------------


def _cell(cells: list[str], mapping: dict[str, int], name: str) -> str:
    index = mapping.get(name)
    if index is None or index >= len(cells):
        return ""
    return cells[index].strip()


def _parse_date(text: str, formats: tuple[str, ...]) -> date | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007 - a calendar date, no time
        except ValueError:
            continue
    return None


def _parse_balance(text: str) -> Decimal:
    """Closing balances may carry a Cr/Dr suffix; Dr means overdrawn (negative)."""
    value = text.strip()
    lowered = value.casefold()
    negative = False
    if lowered.endswith("dr"):
        negative, value = True, value[:-2]
    elif lowered.endswith("cr"):
        value = value[:-2]
    amount = parse_money(value)
    return -amount if negative and amount > 0 else amount


def _amount_or_none(text: str) -> Decimal | None:
    """Blank, '-' and zero all mean "no amount in this column"."""
    if text in {"", "-"}:
        return None
    amount = parse_money(text)
    return None if amount == 0 else amount


def _invalid(row: ParsedRow, code: str, message: str) -> ParsedRow:
    row.status, row.error_code, row.error_message = "invalid", code, message
    return row


def _parse_amount(
    row: ParsedRow, cells: list[str], mapping: dict[str, int], profile: ImportProfile
) -> ParsedRow | None:
    """Set amount and direction on ``row``; return the row as invalid on failure."""
    try:
        if profile.amount_mode == "split":
            debit = _amount_or_none(_cell(cells, mapping, "debit"))
            credit = _amount_or_none(_cell(cells, mapping, "credit"))
        else:
            signed_text = _cell(cells, mapping, "amount")
            if not signed_text:
                debit = credit = None
            else:
                signed = parse_money(signed_text)
                debit = -signed if signed < 0 else None
                credit = signed if signed > 0 else None
    except MoneyFormatError:
        return _invalid(
            row,
            "import.row.bad_amount",
            "The amount is not a number with at most 2 decimals.",
        )
    if (debit is not None and debit < 0) or (credit is not None and credit < 0):
        return _invalid(
            row, "import.row.bad_amount", "Withdrawal and deposit amounts cannot be negative."
        )
    if debit is not None and credit is not None:
        return _invalid(
            row,
            "import.row.two_amounts",
            "The row has both a withdrawal and a deposit; it should have one.",
        )
    if debit is None and credit is None:
        return _invalid(row, "import.row.no_amount", "The row has no amount.")
    row.amount, row.direction = (debit, "debit") if debit is not None else (credit, "credit")
    return None


def _parse_row(
    line: int, cells: list[str], mapping: dict[str, int], profile: ImportProfile
) -> tuple[ParsedRow, str | None]:
    """Returns the row and an optional warning code for non-fatal problems."""
    raw_hash = hashlib.sha256("\x1f".join(cells).encode("utf-8")).hexdigest()
    row = ParsedRow(row_number=line, raw_hash=raw_hash, status="valid")

    description = " ".join(_cell(cells, mapping, "narration").split())
    row.description = description[:MAX_DESCRIPTION] or None
    reference = _cell(cells, mapping, "reference")
    # Banks print "0000000000" when there is no cheque/reference number.
    row.reference = reference[:MAX_REFERENCE] if reference and reference.strip("0") else None

    posted_on = _parse_date(_cell(cells, mapping, "date"), profile.date_formats)
    if posted_on is None:
        return (
            _invalid(
                row,
                "import.row.bad_date",
                "The date could not be read (expected a date like 05/11/2026).",
            ),
            None,
        )
    row.posted_on = posted_on
    value_date_text = _cell(cells, mapping, "value_date")
    row.value_date = _parse_date(value_date_text, profile.date_formats) if value_date_text else None

    failed = _parse_amount(row, cells, mapping, profile)
    if failed is not None:
        return failed, None

    warning = None
    balance_text = _cell(cells, mapping, "balance")
    if balance_text:
        try:
            row.closing_balance = _parse_balance(balance_text)
        except MoneyFormatError:
            warning = "import.row.bad_balance"
    return row, warning


def _first_cell(cells: list[str]) -> str | None:
    for cell in cells:
        if cell.strip():
            return cell.strip().casefold()
    return None


# --- whole statement ------------------------------------------------------------------------


def parse_statement(data: bytes, profile: ImportProfile, *, max_rows: int) -> ParsedStatement:
    records = _read_csv(decode_bytes(data))
    header_index, mapping = _find_header(records, profile)
    header_line = records[header_index][0]

    rows: list[ParsedRow] = []
    ignored = 0
    warnings: list[dict[str, object]] = []
    for line, cells in records[header_index + 1 :]:
        first = _first_cell(cells)
        if first is not None and first.startswith(profile.footer_prefixes):
            break  # bank summary/totals footer
        if first is None or first.startswith(profile.ignore_prefixes):
            ignored += 1
            continue
        if len(rows) >= max_rows:
            raise ImportFileError(
                422,
                "import.too_many_rows",
                f"The file has more than {max_rows} transaction rows; split it into smaller files.",
            )
        row, warning = _parse_row(line, cells, mapping, profile)
        rows.append(row)
        if warning:
            _warn(warnings, warning, "The closing balance could not be read.", line)

    if not rows:
        raise ImportFileError(
            422, "import.no_rows", "The file has a header but no transaction rows."
        )

    statement = ParsedStatement(
        header_row_number=header_line, rows=rows, ignored_rows=ignored, warnings=warnings
    )
    _mark_duplicates_in_file(statement)
    _check_balances(statement)
    return statement


def _warn(warnings: list[dict[str, object]], code: str, message: str, row: int | None) -> None:
    if len(warnings) < MAX_WARNINGS:
        warnings.append({"code": code, "message": message, "row_number": row})


def _mark_duplicates_in_file(statement: ParsedStatement) -> None:
    """Identical rows are normally kept (two ₹20 chai payments are real). But two identical
    rows that also share the same bank reference number are one transaction printed twice."""
    seen: set[tuple[str, ...]] = set()
    for row in statement.valid_rows:
        if row.reference is None:
            continue
        key = row.statement_row().base_key()
        if key in seen:
            row.status = "duplicate_in_file"
            row.error_code = "import.row.duplicate_in_file"
            row.error_message = "Same date, amount, description and reference as an earlier row."
        seen.add(key)


def chronological(rows: list[ParsedRow]) -> list[ParsedRow]:
    """Banks export oldest-first or newest-first; return oldest-first, keeping same-day order."""
    dates = [r.posted_on for r in rows if r.posted_on is not None]
    if len(dates) >= 2 and dates[0] > dates[-1]:
        return list(reversed(rows))
    return list(rows)


def _check_balances(statement: ParsedStatement) -> None:
    """Running-balance check and closing balance. Reports problems; never changes data."""
    ordered = chronological([r for r in statement.rows if r.status != "invalid"])
    if not ordered:
        return
    with_balance = [r for r in ordered if r.closing_balance is not None]
    if with_balance:
        last = with_balance[-1]
        statement.closing_balance = last.closing_balance
        statement.closing_balance_on = last.posted_on

    if len(with_balance) != len(ordered) or len(ordered) < 2:
        return
    broken = 0
    for previous, current in itertools.pairwise(ordered):
        if previous.closing_balance is None or current.closing_balance is None:
            continue  # unreachable: every row here has a balance; keeps types exact
        if previous.closing_balance + current.signed_amount != current.closing_balance:
            broken += 1
            _warn(
                statement.warnings,
                "import.balance_chain_broken",
                "The closing balance does not follow from the previous row "
                "(a row may be missing or wrong).",
                current.row_number,
            )
    if any(r.status == "invalid" for r in statement.rows) and broken:
        _warn(
            statement.warnings,
            "import.invalid_rows_present",
            "Some rows could not be read, so the closing balances do not chain.",
            None,
        )
