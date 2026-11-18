"""accounts: last4 and archive flag; categories: archive flag

Revision ID: 47ad561c3709
Revises: 76fecd5c47c9
Create Date: 2026-11-18 04:00:00

Accounts and categories are never deleted (transactions point at them); they
are archived instead, which hides them from default lists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "47ad561c3709"
down_revision: str | Sequence[str] | None = "76fecd5c47c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("financial_accounts", sa.Column("last4", sa.String(length=4), nullable=True))
    op.add_column(
        "financial_accounts",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_financial_accounts_valid_last4"),
        "financial_accounts",
        "last4 IS NULL OR last4 ~ '^[0-9]{4}$'",
    )
    op.add_column(
        "categories",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("categories", "is_archived")
    op.drop_constraint(
        op.f("ck_financial_accounts_valid_last4"), "financial_accounts", type_="check"
    )
    op.drop_column("financial_accounts", "is_archived")
    op.drop_column("financial_accounts", "last4")
