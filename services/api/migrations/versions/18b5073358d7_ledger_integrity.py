"""ledger integrity: immutable facts, audit events, transfer group check

Revision ID: 18b5073358d7
Revises: 81156a5ea811
Create Date: 2026-11-18 06:00:00

- transactions: user-editable `notes`, `category_source`, `is_excluded`.
- trigger `transactions_facts_immutable`: an UPDATE that changes any source fact
  (amount, date, description, account, ...) is rejected by the database itself.
- transaction_events: append-only history; a trigger rejects UPDATE and DELETE.
- constraint trigger `transactions_transfer_group_valid` (deferred to commit): a
  transfer group has exactly one debit and one credit, equal amounts, two
  different accounts, one user.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "18b5073358d7"
down_revision: str | Sequence[str] | None = "81156a5ea811"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACT_COLUMNS = (
    "id",
    "user_id",
    "account_id",
    "amount",
    "direction",
    "posted_on",
    "occurred_at",
    "description",
    "source",
    "external_id",
    "fingerprint",
    "import_id",
    "import_row_number",
    "created_at",
)

IMMUTABLE_FUNCTION = """
CREATE FUNCTION transactions_reject_fact_changes() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF {checks} THEN
        RAISE EXCEPTION 'transaction source facts cannot be changed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
""".format(checks="\n       OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in FACT_COLUMNS))

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION transaction_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'transaction events are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
"""

TRANSFER_GROUP_FUNCTION = """
CREATE FUNCTION transactions_check_transfer_group() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    group_id uuid;
    total int; debits int; credits int; accounts int; amounts int; users int;
BEGIN
    FOREACH group_id IN ARRAY ARRAY[
        NEW.transfer_group_id,
        CASE WHEN TG_OP = 'UPDATE' THEN OLD.transfer_group_id END
    ] LOOP
        CONTINUE WHEN group_id IS NULL;
        SELECT count(*),
               count(*) FILTER (WHERE direction = 'debit'),
               count(*) FILTER (WHERE direction = 'credit'),
               count(DISTINCT account_id),
               count(DISTINCT amount),
               count(DISTINCT user_id)
          INTO total, debits, credits, accounts, amounts, users
          FROM transactions WHERE transfer_group_id = group_id;
        IF total <> 0 AND NOT (total = 2 AND debits = 1 AND credits = 1
                               AND accounts = 2 AND amounts = 1 AND users = 1) THEN
            RAISE EXCEPTION 'transfer group must be one debit and one credit of equal amounts '
                            'in two different accounts'
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$;
"""


def upgrade() -> None:
    op.add_column("transactions", sa.Column("notes", sa.String(length=1000), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("category_source", sa.String(length=10), server_default="none", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("is_excluded", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Categories set before this migration were chosen by a person (manual entries).
    op.execute("UPDATE transactions SET category_source = 'user' WHERE category_id IS NOT NULL")
    op.create_check_constraint(
        op.f("ck_transactions_valid_category_source"),
        "transactions",
        "category_source IN ('rule', 'user', 'system', 'none')",
    )

    op.create_table(
        "transaction_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor IN ('user', 'system', 'rule')", name=op.f("ck_transaction_events_valid_actor")
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name="fk_event_transaction_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_transaction_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_events")),
        sa.UniqueConstraint("seq", name="uq_transaction_events_seq"),
    )
    op.create_index("ix_transaction_events_tx_seq", "transaction_events", ["transaction_id", "seq"])

    op.execute(IMMUTABLE_FUNCTION)
    op.execute(
        "CREATE TRIGGER transactions_facts_immutable BEFORE UPDATE ON transactions "
        "FOR EACH ROW EXECUTE FUNCTION transactions_reject_fact_changes()"
    )
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(
        "CREATE TRIGGER transaction_events_no_update_delete BEFORE UPDATE OR DELETE "
        "ON transaction_events FOR EACH ROW EXECUTE FUNCTION transaction_events_append_only()"
    )
    op.execute(TRANSFER_GROUP_FUNCTION)
    op.execute(
        "CREATE CONSTRAINT TRIGGER transactions_transfer_group_valid_insert "
        "AFTER INSERT ON transactions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "WHEN (NEW.transfer_group_id IS NOT NULL) "
        "EXECUTE FUNCTION transactions_check_transfer_group()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER transactions_transfer_group_valid_update "
        "AFTER UPDATE OF transfer_group_id ON transactions DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW WHEN (OLD.transfer_group_id IS DISTINCT FROM NEW.transfer_group_id) "
        "EXECUTE FUNCTION transactions_check_transfer_group()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER transactions_transfer_group_valid_update ON transactions")
    op.execute("DROP TRIGGER transactions_transfer_group_valid_insert ON transactions")
    op.execute("DROP FUNCTION transactions_check_transfer_group()")
    op.execute("DROP TRIGGER transaction_events_no_update_delete ON transaction_events")
    op.execute("DROP FUNCTION transaction_events_append_only()")
    op.execute("DROP TRIGGER transactions_facts_immutable ON transactions")
    op.execute("DROP FUNCTION transactions_reject_fact_changes()")
    op.drop_index("ix_transaction_events_tx_seq", table_name="transaction_events")
    op.drop_table("transaction_events")
    op.drop_constraint(op.f("ck_transactions_valid_category_source"), "transactions", type_="check")
    op.drop_column("transactions", "is_excluded")
    op.drop_column("transactions", "category_source")
    op.drop_column("transactions", "notes")
