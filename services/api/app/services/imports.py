"""CSV statement import: upload -> preview -> commit (handoff section 8).

Upload parses everything at once (files are small) into ``import_rows`` and
returns a preview. Nothing touches the ledger until the user commits. Commit is
one database transaction that inserts new rows, records the statement's
closing balance, and enqueues categorization. Committing twice is harmless.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.domain.fingerprint import fingerprint_rows
from app.importers.parser import ImportFileError, ParsedStatement, parse_statement
from app.importers.profiles import PROFILES, ImportProfile
from app.jobs.queue import enqueue
from app.models import (
    BalanceSnapshot,
    FinancialAccount,
    ImportRow,
    Job,
    Transaction,
    TransactionImport,
)
from app.repositories.common import get_owned_or_404
from app.services import audit

CATEGORIZE_KIND = "categorize_import"
ACCEPTED_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "text/plain",
    "application/vnd.ms-excel",  # how Windows browsers label .csv files
    "application/octet-stream",
    "",
}


def categorize_key(import_id: UUID) -> str:
    return f"{CATEGORIZE_KIND}:{import_id}"


def get_profile(profile_id: str) -> ImportProfile:
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise ProblemError(
            422, "import.unknown_profile", "Unknown profile", "Choose one of the import profiles."
        )
    return profile


def check_upload_metadata(filename: str | None, content_type: str | None) -> None:
    if not filename or not filename.lower().endswith(".csv"):
        raise ProblemError(
            415, "import.unsupported_type", "Unsupported file", "Only .csv files can be imported."
        )
    base_type = (content_type or "").split(";")[0].strip().lower()
    if base_type not in ACCEPTED_CONTENT_TYPES:
        raise ProblemError(
            415, "import.unsupported_type", "Unsupported file", "Only .csv files can be imported."
        )


@dataclass(frozen=True)
class UploadedFile:
    data: bytes
    filename: str | None
    content_type: str | None


def create_import(
    session: Session,
    user_id: UUID,
    *,
    account_id: UUID,
    profile_id: str,
    upload: UploadedFile,
    max_rows: int,
) -> TransactionImport:
    account = get_owned_or_404(session, FinancialAccount, account_id, user_id, "account")
    if account.is_archived:
        raise ProblemError(409, "account.archived", "Account archived", "This account is archived.")
    profile = get_profile(profile_id)
    check_upload_metadata(upload.filename, upload.content_type)
    file_sha256 = hashlib.sha256(upload.data).hexdigest()

    _clear_previous_attempt(session, user_id, account_id, file_sha256)

    try:
        statement = parse_statement(upload.data, profile, max_rows=max_rows)
    except ImportFileError as exc:
        failed = _new_import(session, user_id, account_id, profile, file_sha256, upload)
        failed.status, failed.error_message = "failed", exc.message
        audit.record(
            session,
            user_id=user_id,
            action="import_rejected",
            resource_id=failed.id,
            details={"code": exc.code},
        )
        session.commit()
        raise ProblemError(
            exc.status,
            exc.code,
            "Import rejected",
            exc.message,
            extra={"import_id": str(failed.id)},
        ) from exc

    record = _new_import(session, user_id, account_id, profile, file_sha256, upload)
    _stage_rows(session, user_id, record, statement)
    audit.record(
        session,
        user_id=user_id,
        action="import_uploaded",
        resource_id=record.id,
        details={"profile_id": profile.id, "rows_total": record.rows_total},
    )
    try:
        session.commit()
    except IntegrityError as exc:  # the same file uploaded twice at the same moment
        session.rollback()
        raise ProblemError(
            409, "import.in_progress", "Import in progress", "This file is already being imported."
        ) from exc
    return record


def _clear_previous_attempt(
    session: Session, user_id: UUID, account_id: UUID, file_sha256: str
) -> None:
    """A completed import of the same file is a conflict; any other attempt is replaced."""
    previous = session.scalars(
        select(TransactionImport).where(
            TransactionImport.user_id == user_id,
            TransactionImport.account_id == account_id,
            TransactionImport.file_sha256 == file_sha256,
        )
    ).first()
    if previous is None:
        return
    if previous.status == "completed":
        raise ProblemError(
            409,
            "import.already_imported",
            "Already imported",
            "This exact file was already imported into this account.",
            extra={"import_id": str(previous.id)},
        )
    # Failed, cancelled or never-committed previews hold no ledger rows: replace them.
    session.delete(previous)
    session.flush()


def _new_import(
    session: Session,
    user_id: UUID,
    account_id: UUID,
    profile: ImportProfile,
    file_sha256: str,
    upload: UploadedFile,
) -> TransactionImport:
    record = TransactionImport(
        user_id=user_id,
        account_id=account_id,
        source=f"csv:{profile.id}",
        profile_id=profile.id,
        file_sha256=file_sha256,
        file_size_bytes=len(upload.data),
        status="pending",
        rows_total=0,
        rows_imported=0,
        rows_skipped=0,
        rows_failed=0,
        warnings=[],
    )
    session.add(record)
    session.flush()
    return record


def _stage_rows(
    session: Session, user_id: UUID, record: TransactionImport, statement: ParsedStatement
) -> None:
    valid = statement.valid_rows
    fingerprints = fingerprint_rows(record.account_id, [r.statement_row() for r in valid])
    by_row = {row.row_number: fp for row, fp in zip(valid, fingerprints, strict=True)}
    # A row printed twice points at the fingerprint of the row it repeats.
    first_by_key: dict[tuple[str, ...], str] = {}
    for row, fp in zip(valid, fingerprints, strict=True):
        first_by_key.setdefault(row.statement_row().base_key(), fp)
    existing = set(
        session.scalars(
            select(Transaction.fingerprint).where(
                Transaction.user_id == user_id,
                Transaction.account_id == record.account_id,
                Transaction.fingerprint.in_(fingerprints),
            )
        )
    )

    staged: list[dict[str, Any]] = []
    for row in statement.rows:
        status: str = row.status
        fingerprint = by_row.get(row.row_number)
        if row.status == "duplicate_in_file":
            fingerprint = first_by_key.get(row.statement_row().base_key())
        if status == "valid" and fingerprint in existing:
            status = "already_imported"
        staged.append(
            {
                "user_id": user_id,
                "import_id": record.id,
                "row_number": row.row_number,
                "raw_hash": row.raw_hash,
                "status": status,
                "posted_on": row.posted_on,
                "value_date": row.value_date,
                "description": row.description,
                "reference": row.reference,
                "amount": row.amount,
                "direction": row.direction,
                "closing_balance": row.closing_balance,
                "fingerprint": fingerprint if row.status != "invalid" else None,
                "error_code": row.error_code,
                "error_message": row.error_message,
            }
        )
    session.execute(insert(ImportRow), staged)

    statuses = [s["status"] for s in staged]
    dates = [r.posted_on for r in valid if r.posted_on is not None]
    record.status = "previewed"
    record.rows_total = len(staged)
    record.rows_failed = statuses.count("invalid")
    record.rows_skipped = statuses.count("duplicate_in_file") + statuses.count("already_imported")
    record.date_from = min(dates) if dates else None
    record.date_to = max(dates) if dates else None
    record.closing_balance = statement.closing_balance
    record.closing_balance_on = statement.closing_balance_on
    record.warnings = list(statement.warnings)
    session.flush()


def commit_import(session: Session, user_id: UUID, import_id: UUID, now: datetime) -> None:
    record = get_owned_or_404(
        session, TransactionImport, import_id, user_id, "import", for_update=True
    )
    if record.status == "completed":
        return  # idempotent: committing again changes nothing
    if record.status != "previewed":
        raise ProblemError(
            409,
            "import.not_committable",
            "Import cannot be committed",
            f"An import that is {record.status} cannot be committed.",
        )

    valid = list(
        session.scalars(
            select(ImportRow)
            .where(ImportRow.import_id == record.id, ImportRow.status == "valid")
            .order_by(ImportRow.row_number)
        )
    )
    inserted: set[str] = set()
    if valid:
        result = session.execute(
            insert(Transaction)
            .values(
                [
                    {
                        "user_id": user_id,
                        "account_id": record.account_id,
                        "import_id": record.id,
                        "import_row_number": row.row_number,
                        "amount": row.amount,
                        "direction": row.direction,
                        "transaction_type": "expense" if row.direction == "debit" else "income",
                        "description": row.description,
                        "source": record.source,
                        "fingerprint": row.fingerprint,
                        "posted_on": row.posted_on,
                    }
                    for row in valid
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[Transaction.account_id, Transaction.fingerprint]
            )
            .returning(Transaction.fingerprint)
        )
        inserted = set(result.scalars())
    # Rows imported meanwhile by another file are skipped, and marked so in the preview.
    raced = [row.fingerprint for row in valid if row.fingerprint not in inserted]
    if raced:
        session.execute(
            update(ImportRow)
            .where(ImportRow.import_id == record.id, ImportRow.fingerprint.in_(raced))
            .values(status="already_imported")
        )

    _record_statement_balance(session, user_id, record)
    record.rows_imported = len(inserted)
    record.rows_skipped += len(raced)
    record.status = "completed"
    record.completed_at = now
    enqueue(
        session,
        kind=CATEGORIZE_KIND,
        payload={"import_id": str(record.id)},
        idempotency_key=categorize_key(record.id),
        user_id=user_id,
    )
    audit.record(
        session,
        user_id=user_id,
        action="import_committed",
        resource_id=record.id,
        details={"rows_imported": record.rows_imported},
    )
    session.commit()


def _record_statement_balance(session: Session, user_id: UUID, record: TransactionImport) -> None:
    """The statement's closing balance becomes a statement snapshot. If another statement
    already gave a different balance for that date, keep it and warn; never overwrite."""
    if record.closing_balance is None or record.closing_balance_on is None:
        return
    existing = session.scalars(
        select(BalanceSnapshot).where(
            BalanceSnapshot.user_id == user_id,
            BalanceSnapshot.account_id == record.account_id,
            BalanceSnapshot.as_of == record.closing_balance_on,
            BalanceSnapshot.source == "statement",
        )
    ).first()
    if existing is None:
        session.add(
            BalanceSnapshot(
                user_id=user_id,
                account_id=record.account_id,
                import_id=record.id,
                as_of=record.closing_balance_on,
                balance=record.closing_balance,
                source="statement",
            )
        )
    elif existing.balance != record.closing_balance:
        record.warnings = [
            *record.warnings,
            {
                "code": "import.closing_balance_conflict",
                "message": "An earlier statement gave a different closing balance for this date; "
                "the earlier one is kept.",
                "row_number": None,
            },
        ]


def cancel_import(session: Session, user_id: UUID, import_id: UUID) -> None:
    record = get_owned_or_404(
        session, TransactionImport, import_id, user_id, "import", for_update=True
    )
    if record.status == "cancelled":
        return
    if record.status != "previewed":
        raise ProblemError(
            409,
            "import.not_cancellable",
            "Import cannot be cancelled",
            f"An import that is {record.status} cannot be cancelled.",
        )
    session.execute(delete(ImportRow).where(ImportRow.import_id == record.id))
    record.status = "cancelled"
    session.commit()


# --- reads -----------------------------------------------------------------------------------


def list_imports(session: Session, user_id: UUID) -> list[TransactionImport]:
    return list(
        session.scalars(
            select(TransactionImport)
            .where(TransactionImport.user_id == user_id)
            .order_by(TransactionImport.created_at.desc(), TransactionImport.id.desc())
        )
    )


def get_import(session: Session, user_id: UUID, import_id: UUID) -> TransactionImport:
    return get_owned_or_404(session, TransactionImport, import_id, user_id, "import")


def row_counts(session: Session, import_id: UUID) -> dict[str, int]:
    counts = {"valid": 0, "invalid": 0, "duplicate_in_file": 0, "already_imported": 0}
    for status, count in session.execute(
        select(ImportRow.status, func.count())
        .where(ImportRow.import_id == import_id)
        .group_by(ImportRow.status)
    ):
        counts[status] = count
    return counts


def preview_rows(
    session: Session, import_id: UUID, *, status: str | None, offset: int, limit: int
) -> list[ImportRow]:
    statement = select(ImportRow).where(ImportRow.import_id == import_id)
    if status is not None:
        statement = statement.where(ImportRow.status == status)
    return list(
        session.scalars(statement.order_by(ImportRow.row_number).offset(offset).limit(limit))
    )


def categorize_job_id(session: Session, import_id: UUID) -> UUID | None:
    return session.scalars(
        select(Job.id).where(Job.idempotency_key == categorize_key(import_id))
    ).first()
