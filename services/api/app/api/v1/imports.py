"""CSV statement imports: profiles, upload + preview, commit, cancel."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.core.clock import Clock
from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_clock
from app.core.errors import ProblemError
from app.importers.profiles import PROFILES
from app.models import TransactionImport
from app.schemas.imports import (
    ImportList,
    ImportOut,
    ImportProfileList,
    ImportProfileOut,
    ImportRowOut,
    ImportSummary,
    ImportWarning,
    RowCounts,
    RowStatus,
)
from app.services import imports as service

router = APIRouter(tags=["imports"])
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]


@router.get("/import-profiles", response_model=ImportProfileList)
def list_profiles() -> ImportProfileList:
    return ImportProfileList(
        items=[
            ImportProfileOut(
                id=p.id,
                label=p.label,
                description=p.description,
                verified=p.verified,
                verification_note=p.verification_note,
            )
            for p in PROFILES.values()
        ]
    )


def import_out(
    session: DbSession,
    record: TransactionImport,
    *,
    row_status: str | None = None,
    row_offset: int = 0,
    row_limit: int = 50,
) -> ImportOut:
    profile = PROFILES.get(record.profile_id or "")
    rows = service.preview_rows(
        session, record.id, status=row_status, offset=row_offset, limit=row_limit
    )
    return ImportOut(
        **ImportSummary.model_validate(record).model_dump(),
        profile_verified=profile.verified if profile else None,
        profile_note=profile.verification_note if profile else None,
        file_size_bytes=record.file_size_bytes,
        counts=RowCounts(**service.row_counts(session, record.id)),
        closing_balance=record.closing_balance,
        closing_balance_on=record.closing_balance_on,
        warnings=[ImportWarning.model_validate(w) for w in record.warnings],
        rows=[ImportRowOut.model_validate(r) for r in rows],
        categorize_job_id=service.categorize_job_id(session, record.id),
    )


@router.post("/imports", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
def upload_statement(
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="The bank statement as a .csv file")],
    account_id: Annotated[UUID, Form()],
    profile_id: Annotated[str, Form(max_length=60)],
) -> ImportOut:
    """Upload and preview. Nothing is added to your transactions until you commit."""
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ProblemError(
            413,
            "import.file_too_large",
            "File too large",
            f"The file is larger than {settings.max_upload_bytes // (1024 * 1024)} MB.",
        )
    record = service.create_import(
        session,
        user.id,
        account_id=account_id,
        profile_id=profile_id,
        upload=service.UploadedFile(data, file.filename, file.content_type),
        max_rows=settings.max_import_rows,
    )
    return import_out(session, record)


@router.get("/imports", response_model=ImportList)
def list_imports(user: CurrentUser, session: DbSession) -> ImportList:
    return ImportList(
        items=[ImportSummary.model_validate(r) for r in service.list_imports(session, user.id)]
    )


@router.get("/imports/{import_id}", response_model=ImportOut)
def read_import(
    import_id: UUID,
    user: CurrentUser,
    session: DbSession,
    row_status: RowStatus | None = None,
    row_offset: Annotated[int, Query(ge=0)] = 0,
    row_limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ImportOut:
    record = service.get_import(session, user.id, import_id)
    return import_out(
        session, record, row_status=row_status, row_offset=row_offset, row_limit=row_limit
    )


@router.post("/imports/{import_id}/commit", response_model=ImportOut)
def commit_import(
    import_id: UUID, user: CurrentUser, session: DbSession, clock: ClockDep
) -> ImportOut:
    """Add the valid rows to your transactions. Safe to call more than once."""
    service.commit_import(session, user.id, import_id, clock.now())
    return import_out(session, service.get_import(session, user.id, import_id))


@router.post("/imports/{import_id}/cancel", response_model=ImportOut)
def cancel_import(import_id: UUID, user: CurrentUser, session: DbSession) -> ImportOut:
    service.cancel_import(session, user.id, import_id)
    return import_out(session, service.get_import(session, user.id, import_id))
