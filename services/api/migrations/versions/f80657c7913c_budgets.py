"""budgets: monthly spending limits per category or for all spending

Revision ID: f80657c7913c
Revises: 18b5073358d7
Create Date: 2026-11-18 18:00:00

`category_id` NULL means "all spending". The unique key uses NULLS NOT DISTINCT
(PostgreSQL 15+) so there can be only one all-spending budget per month.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f80657c7913c"
down_revision: str | Sequence[str] | None = "18b5073358d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("warn_at_percent", sa.Integer(), server_default="80", nullable=False),
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
        sa.CheckConstraint("amount > 0", name=op.f("ck_budgets_positive_amount")),
        sa.CheckConstraint(
            "warn_at_percent BETWEEN 1 AND 100", name=op.f("ck_budgets_valid_warn_percent")
        ),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM month) = 1", name=op.f("ck_budgets_month_is_first_day")
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_budget_category_owner",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_budgets_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_budgets_id")),
        sa.UniqueConstraint(
            "user_id",
            "category_id",
            "month",
            name="uq_budgets_user_category_month",
            postgresql_nulls_not_distinct=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("budgets")
