"""Job handlers by kind. Each one is idempotent."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.jobs.runner import Handler
from app.models import Job, TransactionImport
from app.services.categorization import categorize_import


class JobPayloadError(Exception):
    """The job's payload does not describe work this handler can do."""


def handle_categorize_import(session: Session, job: Job) -> None:
    """Apply categorization rules to an import's uncategorized rows (actor ``rule``)."""
    if job.user_id is None:
        raise JobPayloadError("categorize_import needs a user")
    import_id = UUID(str(job.payload["import_id"]))
    record = session.get(TransactionImport, import_id)
    if record is None or record.user_id != job.user_id or record.status != "completed":
        raise JobPayloadError("import not found or not completed")
    categorize_import(session, job.user_id, import_id)


HANDLERS: dict[str, Handler] = {
    "categorize_import": handle_categorize_import,
}
