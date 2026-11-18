"""goals and wishlist with an append-only event history

Revision ID: c4396ad9d251
Revises: f80657c7913c
Create Date: 2026-11-18 19:00:00

The saved amount is derived from goal_events (contributions minus withdrawals),
never stored. A trigger rejects UPDATE and DELETE on goal_events.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4396ad9d251"
down_revision: str | Sequence[str] | None = "f80657c7913c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = """
CREATE FUNCTION goal_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'goal events are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("target_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("item_url", sa.String(length=2000), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
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
        sa.CheckConstraint("kind IN ('wishlist', 'savings')", name=op.f("ck_goals_valid_kind")),
        sa.CheckConstraint("target_amount > 0", name=op.f("ck_goals_positive_target")),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name=op.f("ck_goals_valid_priority")),
        sa.CheckConstraint(
            "status IN ('active', 'achieved', 'abandoned')", name=op.f("ck_goals_valid_status")
        ),
        sa.CheckConstraint(
            "item_url IS NULL OR item_url ~* '^https?://'", name=op.f("ck_goals_item_url_is_http")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_goals_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goals")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_goals_id")),
    )
    op.create_index("ix_goals_user", "goals", ["user_id"])
    op.create_table(
        "goal_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("actor", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'target_changed', 'date_changed', 'details_changed', "
            "'contribution', 'withdrawal', 'status_changed', 'note')",
            name=op.f("ck_goal_events_valid_event_type"),
        ),
        sa.CheckConstraint(
            "(event_type IN ('contribution', 'withdrawal')) = (amount IS NOT NULL)",
            name=op.f("ck_goal_events_amount_only_on_money_events"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0", name=op.f("ck_goal_events_positive_amount")
        ),
        sa.CheckConstraint("actor IN ('user', 'system')", name=op.f("ck_goal_events_valid_actor")),
        sa.ForeignKeyConstraint(
            ["goal_id", "user_id"], ["goals.id", "goals.user_id"], name="fk_goal_event_owner"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_goal_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_events")),
        sa.UniqueConstraint("seq", name="uq_goal_events_seq"),
    )
    op.create_index("ix_goal_events_goal_seq", "goal_events", ["goal_id", "seq"])
    op.execute(APPEND_ONLY)
    op.execute(
        "CREATE TRIGGER goal_events_no_update_delete BEFORE UPDATE OR DELETE ON goal_events "
        "FOR EACH ROW EXECUTE FUNCTION goal_events_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER goal_events_no_update_delete ON goal_events")
    op.execute("DROP FUNCTION goal_events_append_only()")
    op.drop_index("ix_goal_events_goal_seq", table_name="goal_events")
    op.drop_table("goal_events")
    op.drop_index("ix_goals_user", table_name="goals")
    op.drop_table("goals")
