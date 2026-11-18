"""Download everything the API holds about you (journey 12)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, DbSession
from app.core.clock import Clock
from app.core.dependencies import get_clock
from app.services import audit
from app.services.export import build_export, to_zip

router = APIRouter(tags=["export"])
ClockDep = Annotated[Clock, Depends(get_clock)]


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "A zip of your data"}},
)
def export_my_data(user: CurrentUser, session: DbSession, clock: ClockDep) -> Response:
    """A zip with transactions.csv, accounts.json, categories.json, budgets.json, goals.json,
    imports.json, transaction_events.json and manifest.json (row counts and SHA-256 per file)."""
    files = build_export(session, user.id)
    audit.record(session, user_id=user.id, action="data_exported", details={"files": len(files)})
    session.commit()
    filename = f"finance-ai-export-{clock.today().isoformat()}.zip"
    return Response(
        content=to_zip(files),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
