"""CSV import pipeline: staging rows, jobs outbox, access audit

Revision ID: 81156a5ea811
Revises: 47ad561c3709
Create Date: 2026-11-18 05:00:00

- transaction_imports: statuses previewed/cancelled; profile, file size, date range,
  detected closing balance and preview warnings (the file itself is never stored).
- transactions.import_row_number: which line of the file a row came from.
- import_rows: parsed preview rows (deleted with their import).
- jobs: PostgreSQL outbox for background work (worker arrives in M5).
- access_audit: imports, exports and repeated sign-in failures (no secrets, no amounts).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "81156a5ea811"
down_revision: str | Sequence[str] | None = "47ad561c3709"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "status IN ('pending', 'processing', 'completed', 'failed')"
NEW_STATUSES = (
    "status IN ('pending', 'previewed', 'processing', 'completed', 'failed', 'cancelled')"
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_transaction_imports_valid_import_status"), "transaction_imports", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_transaction_imports_valid_import_status"), "transaction_imports", NEW_STATUSES
    )
    op.add_column("transaction_imports", sa.Column("profile_id", sa.String(60), nullable=True))
    op.add_column("transaction_imports", sa.Column("file_size_bytes", sa.Integer(), nullable=True))
    op.add_column("transaction_imports", sa.Column("date_from", sa.Date(), nullable=True))
    op.add_column("transaction_imports", sa.Column("date_to", sa.Date(), nullable=True))
    op.add_column(
        "transaction_imports",
        sa.Column("closing_balance", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.add_column("transaction_imports", sa.Column("closing_balance_on", sa.Date(), nullable=True))
    op.add_column(
        "transaction_imports",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("transactions", sa.Column("import_row_number", sa.Integer(), nullable=True))

    op.create_table(
        "import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("posted_on", sa.Date(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("direction", sa.String(6), nullable=True),
        sa.Column("closing_balance", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_message", sa.String(300), nullable=True),
        sa.CheckConstraint(
            "status IN ('valid', 'invalid', 'duplicate_in_file', 'already_imported')",
            name=op.f("ck_import_rows_valid_row_status"),
        ),
        sa.CheckConstraint(
            "status = 'invalid' OR (posted_on IS NOT NULL AND amount > 0 "
            "AND direction IN ('debit', 'credit') AND fingerprint IS NOT NULL)",
            name=op.f("ck_import_rows_parsed_rows_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["import_id", "user_id"],
            ["transaction_imports.id", "transaction_imports.user_id"],
            name="fk_import_row_import_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_import_rows_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_rows")),
        sa.UniqueConstraint("import_id", "row_number", name="uq_import_rows_import_row"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'dead')",
            name=op.f("ck_jobs_valid_job_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1", name=op.f("ck_jobs_valid_attempts")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_status_run_after", "jobs", ["status", "run_after"])

    op.create_table(
        "access_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_access_audit_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_audit")),
    )
    op.create_index("ix_access_audit_user_created", "access_audit", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_access_audit_user_created", table_name="access_audit")
    op.drop_table("access_audit")
    op.drop_index("ix_jobs_status_run_after", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("import_rows")
    op.drop_column("transactions", "import_row_number")
    for column in (
        "warnings",
        "closing_balance_on",
        "closing_balance",
        "date_to",
        "date_from",
        "file_size_bytes",
        "profile_id",
    ):
        op.drop_column("transaction_imports", column)
    # Imports in the new statuses cannot exist under the old rule.
    op.execute("DELETE FROM transaction_imports WHERE status IN ('previewed', 'cancelled')")
    op.drop_constraint(
        op.f("ck_transaction_imports_valid_import_status"), "transaction_imports", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_transaction_imports_valid_import_status"), "transaction_imports", OLD_STATUSES
    )
