"""CSV mapping profiles: data that describes a statement layout (handoff section 8.2).

Adding a bank means adding a profile here, not new parsing code. Header names
are compared after normalization (lower-case, letters and digits only), so
"Withdrawal Amt." matches "withdrawal amt" and "WITHDRAWAL AMT".
"""

import re
from dataclasses import dataclass, field
from typing import Literal

AmountMode = Literal["split", "signed"]


def normalize_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]", "", cell.casefold())


@dataclass(frozen=True)
class ImportProfile:
    id: str
    label: str
    description: str
    verified: bool
    verification_note: str
    amount_mode: AmountMode
    # field -> accepted header names (first match wins)
    columns: dict[str, tuple[str, ...]]
    required: tuple[str, ...]
    date_formats: tuple[str, ...]
    # Rows whose first non-empty cell starts with one of these are skipped, not errors.
    ignore_prefixes: tuple[str, ...] = field(default=("opening balance", "closing balance"))
    # A row starting with one of these begins the footer: nothing after it is a transaction.
    footer_prefixes: tuple[str, ...] = field(
        default=("statement summary", "total", "***", "end of statement")
    )

    def match_header(self, cells: list[str]) -> dict[str, int] | None:
        """Column index for each field if ``cells`` is this profile's header row."""
        normalized = [normalize_header(c) for c in cells]
        found: dict[str, int] = {}
        for name, aliases in self.columns.items():
            for alias in aliases:
                key = normalize_header(alias)
                if key in normalized:
                    found[name] = normalized.index(key)
                    break
        if all(name in found for name in self.required):
            return found
        return None


INDIAN_DATE_FORMATS = ("%d/%m/%y", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y", "%d-%b-%y", "%d %b %Y")

GENERIC_INDIAN_BANK_V1 = ImportProfile(
    id="generic_indian_bank_v1",
    label="Indian bank statement (generic)",
    description=(
        "Columns: Date, Narration, Chq./Ref.No., Value Dt, Withdrawal Amt., Deposit Amt., "
        "Closing Balance. The layout most Indian bank CSV exports resemble."
    ),
    verified=False,
    verification_note="synthetic, not yet verified against a real export",
    amount_mode="split",
    columns={
        "date": ("Date", "Txn Date", "Transaction Date"),
        "narration": ("Narration", "Description", "Particulars"),
        "reference": ("Chq./Ref.No.", "Chq/Ref No", "Ref No.", "Reference No"),
        "value_date": ("Value Dt", "Value Date"),
        "debit": ("Withdrawal Amt.", "Withdrawal Amount", "Debit"),
        "credit": ("Deposit Amt.", "Deposit Amount", "Credit"),
        "balance": ("Closing Balance", "Balance"),
    },
    required=("date", "narration", "debit", "credit"),
    date_formats=INDIAN_DATE_FORMATS,
)

SIMPLE_V1 = ImportProfile(
    id="simple_v1",
    label="Simple spreadsheet",
    description=(
        "Columns: date, description, amount (negative = money out), optional reference and "
        "balance. For manual spreadsheets and tests."
    ),
    verified=True,
    verification_note="our own format; no bank involved",
    amount_mode="signed",
    columns={
        "date": ("date",),
        "narration": ("description",),
        "amount": ("amount",),
        "reference": ("reference",),
        "balance": ("balance",),
    },
    required=("date", "narration", "amount"),
    date_formats=("%Y-%m-%d", *INDIAN_DATE_FORMATS),
)

PROFILES: dict[str, ImportProfile] = {p.id: p for p in (GENERIC_INDIAN_BANK_V1, SIMPLE_V1)}
