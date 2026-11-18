from datetime import date
from typing import Literal
from uuid import UUID

from app.schemas.common import ApiModel, MoneyOut, UtcDatetime

ImportStatus = Literal["pending", "previewed", "processing", "completed", "failed", "cancelled"]
RowStatus = Literal["valid", "invalid", "duplicate_in_file", "already_imported"]


class ImportProfileOut(ApiModel):
    id: str
    label: str
    description: str
    verified: bool
    verification_note: str


class ImportProfileList(ApiModel):
    items: list[ImportProfileOut]


class ImportWarning(ApiModel):
    code: str
    message: str
    row_number: int | None


class RowCounts(ApiModel):
    valid: int
    invalid: int
    duplicate_in_file: int
    already_imported: int


class ImportRowOut(ApiModel):
    row_number: int
    status: RowStatus
    posted_on: date | None
    value_date: date | None
    description: str | None
    reference: str | None
    amount: MoneyOut | None
    direction: Literal["debit", "credit"] | None
    closing_balance: MoneyOut | None
    error_code: str | None
    error_message: str | None


class ImportSummary(ApiModel):
    id: UUID
    account_id: UUID
    profile_id: str | None
    status: ImportStatus
    created_at: UtcDatetime
    completed_at: UtcDatetime | None
    rows_total: int
    rows_imported: int
    rows_skipped: int
    rows_failed: int
    date_from: date | None
    date_to: date | None
    error_message: str | None


class ImportOut(ImportSummary):
    profile_verified: bool | None
    profile_note: str | None
    file_size_bytes: int | None
    counts: RowCounts
    closing_balance: MoneyOut | None
    closing_balance_on: date | None
    warnings: list[ImportWarning]
    rows: list[ImportRowOut]
    categorize_job_id: UUID | None


class ImportList(ApiModel):
    items: list[ImportSummary]
