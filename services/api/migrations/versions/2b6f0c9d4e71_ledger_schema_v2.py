"""ledger schema v2: fingerprints, dates, transfers, refunds, categories, balances

Revision ID: 2b6f0c9d4e71
Revises: 1173a26c2b83
Create Date: 2026-11-08 02:00:00

What changes and why:
- transactions.fingerprint: duplicate detection that works without a UTR.
- transactions.posted_on: the statement's calendar date, so reports never
  shift a day because of time zones.
- transactions.direction: debit or credit, the bank's fact for this account.
- transfers: each side is its own row, linked by transfer_group_id, because
  the two sides arrive in two different statements.
- refunds: a new type, optionally linked to the original purchase.
- categories, balance_snapshots: new tables.
- transaction_imports: which account, file hash and row counts.

This migration adds NOT NULL columns without defaults, so it refuses to run
if transactions or imports already exist. That is fine today: only synthetic
test data has been used, and the tests roll back their writes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2b6f0c9d4e71"
down_revision: str | Sequence[str] | None = "1173a26c2b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_empty(table: str) -> None:
    count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
    if count:
        raise RuntimeError(
            f"{table} has {count} rows. This migration expects an empty table; "
            "reset your local development database and run it again."
        )


def upgrade() -> None:
    _require_empty("transactions")
    _require_empty("transaction_imports")

    # --- categories (new) -------------------------------------------------
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('expense', 'income')",
            name=op.f("ck_categories_valid_category_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_categories_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_categories_id")),
        sa.UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
    )

    # --- transaction_imports: link to an account, file hash, row counts ---
    op.add_column("transaction_imports", sa.Column("account_id", sa.Uuid(), nullable=False))
    op.add_column(
        "transaction_imports",
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
    )
    for column in ("rows_total", "rows_imported", "rows_skipped", "rows_failed"):
        op.add_column("transaction_imports", sa.Column(column, sa.Integer(), nullable=False))
    op.add_column(
        "transaction_imports",
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "transaction_imports",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_import_account_owner",
        "transaction_imports",
        "financial_accounts",
        ["account_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_unique_constraint(
        "uq_import_account_file", "transaction_imports", ["account_id", "file_sha256"]
    )
    op.create_check_constraint(
        op.f("ck_transaction_imports_valid_row_counts"),
        "transaction_imports",
        "rows_total >= 0 AND rows_imported >= 0 AND rows_skipped >= 0 "
        "AND rows_failed >= 0 "
        "AND rows_imported + rows_skipped + rows_failed <= rows_total",
    )

    # --- transactions: remove the one-row transfer design -----------------
    op.drop_constraint(
        op.f("ck_transactions_valid_transfer_accounts"), "transactions", type_="check"
    )
    op.drop_constraint("fk_tx_destination_owner", "transactions", type_="foreignkey")
    op.drop_column("transactions", "destination_account_id")

    # --- transactions: new columns -----------------------------------------
    op.add_column("transactions", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.add_column("transactions", sa.Column("direction", sa.String(length=6), nullable=False))
    op.add_column("transactions", sa.Column("fingerprint", sa.String(length=64), nullable=False))
    op.add_column("transactions", sa.Column("posted_on", sa.Date(), nullable=False))
    op.add_column("transactions", sa.Column("transfer_group_id", sa.Uuid(), nullable=True))
    op.add_column("transactions", sa.Column("refund_of_id", sa.Uuid(), nullable=True))
    op.alter_column(
        "transactions",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    # --- transactions: keys and links ----------------------------------------
    # (id, user_id) must be unique before a refund can point at it.
    op.create_unique_constraint(op.f("uq_transactions_id"), "transactions", ["id", "user_id"])
    op.create_unique_constraint(
        "uq_tx_account_fingerprint", "transactions", ["account_id", "fingerprint"]
    )
    op.create_foreign_key(
        "fk_tx_category_owner",
        "transactions",
        "categories",
        ["category_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_foreign_key(
        "fk_tx_refund_owner",
        "transactions",
        "transactions",
        ["refund_of_id", "user_id"],
        ["id", "user_id"],
    )

    # --- transactions: rules -------------------------------------------------
    op.drop_constraint(
        op.f("ck_transactions_valid_transaction_type"), "transactions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_transactions_valid_transaction_type"),
        "transactions",
        "transaction_type IN ('income', 'expense', 'transfer', 'refund')",
    )
    op.create_check_constraint(
        op.f("ck_transactions_valid_direction"),
        "transactions",
        "direction IN ('debit', 'credit')",
    )
    op.create_check_constraint(
        op.f("ck_transactions_type_matches_direction"),
        "transactions",
        "(transaction_type = 'expense' AND direction = 'debit') OR "
        "(transaction_type IN ('income', 'refund') AND direction = 'credit') OR "
        "transaction_type = 'transfer'",
    )
    op.create_check_constraint(
        op.f("ck_transactions_transfer_group_only_on_transfers"),
        "transactions",
        "transfer_group_id IS NULL OR transaction_type = 'transfer'",
    )
    op.create_check_constraint(
        op.f("ck_transactions_refund_link_only_on_refunds"),
        "transactions",
        "refund_of_id IS NULL OR (transaction_type = 'refund' AND refund_of_id <> id)",
    )

    # --- transactions: indexes for reports ---------------------------------
    op.drop_index("ix_transactions_user_occurred", table_name="transactions")
    op.create_index("ix_transactions_user_posted", "transactions", ["user_id", "posted_on"])
    op.create_index("ix_transactions_account", "transactions", ["account_id"])
    op.create_index("ix_transactions_transfer_group", "transactions", ["transfer_group_id"])

    # --- balance_snapshots (new) -------------------------------------------
    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('statement', 'user_entered')",
            name=op.f("ck_balance_snapshots_valid_snapshot_source"),
        ),
        sa.CheckConstraint(
            "source <> 'statement' OR import_id IS NOT NULL",
            name=op.f("ck_balance_snapshots_statement_snapshot_has_import"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_snapshot_account_owner",
        ),
        sa.ForeignKeyConstraint(
            ["import_id", "user_id"],
            ["transaction_imports.id", "transaction_imports.user_id"],
            name="fk_snapshot_import_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_balance_snapshots_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_balance_snapshots")),
        sa.UniqueConstraint(
            "account_id", "as_of", "source", name="uq_snapshot_account_date_source"
        ),
    )


def downgrade() -> None:
    _require_empty("transactions")
    _require_empty("transaction_imports")

    op.drop_table("balance_snapshots")

    op.drop_index("ix_transactions_transfer_group", table_name="transactions")
    op.drop_index("ix_transactions_account", table_name="transactions")
    op.drop_index("ix_transactions_user_posted", table_name="transactions")
    op.create_index("ix_transactions_user_occurred", "transactions", ["user_id", "occurred_at"])

    for name in (
        "refund_link_only_on_refunds",
        "transfer_group_only_on_transfers",
        "type_matches_direction",
        "valid_direction",
        "valid_transaction_type",
    ):
        op.drop_constraint(op.f(f"ck_transactions_{name}"), "transactions", type_="check")
    op.create_check_constraint(
        op.f("ck_transactions_valid_transaction_type"),
        "transactions",
        "transaction_type IN ('income', 'expense', 'transfer')",
    )

    op.drop_constraint("fk_tx_refund_owner", "transactions", type_="foreignkey")
    op.drop_constraint("fk_tx_category_owner", "transactions", type_="foreignkey")
    op.drop_constraint("uq_tx_account_fingerprint", "transactions", type_="unique")
    op.drop_constraint(op.f("uq_transactions_id"), "transactions", type_="unique")

    op.alter_column(
        "transactions",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    for column in (
        "refund_of_id",
        "transfer_group_id",
        "posted_on",
        "fingerprint",
        "direction",
        "category_id",
    ):
        op.drop_column("transactions", column)

    op.add_column("transactions", sa.Column("destination_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tx_destination_owner",
        "transactions",
        "financial_accounts",
        ["destination_account_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_check_constraint(
        op.f("ck_transactions_valid_transfer_accounts"),
        "transactions",
        "(transaction_type = 'transfer' AND destination_account_id IS NOT NULL AND "
        "destination_account_id <> account_id) OR "
        "(transaction_type <> 'transfer' AND destination_account_id IS NULL)",
    )

    op.drop_constraint(
        op.f("ck_transaction_imports_valid_row_counts"), "transaction_imports", type_="check"
    )
    op.drop_constraint("uq_import_account_file", "transaction_imports", type_="unique")
    op.drop_constraint("fk_import_account_owner", "transaction_imports", type_="foreignkey")
    for column in (
        "completed_at",
        "error_message",
        "rows_failed",
        "rows_skipped",
        "rows_imported",
        "rows_total",
        "file_sha256",
        "account_id",
    ):
        op.drop_column("transaction_imports", column)

    op.drop_table("categories")
