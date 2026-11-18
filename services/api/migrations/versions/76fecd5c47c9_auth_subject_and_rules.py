"""auth subject on users, case-insensitive email, categorization rules

Revision ID: 76fecd5c47c9
Revises: 2b6f0c9d4e71
Create Date: 2026-11-18 03:00:00

- users.auth_subject: the identity provider's `sub` claim (Supabase user id).
  Existing rows (only possible in a developer's database) get a placeholder
  `legacy:<id>` so the column can be NOT NULL; such users can never sign in.
- users.email: unique ignoring case (index on lower(email)) instead of exact match.
- categorization_rules: merchant pattern -> category, per user.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "76fecd5c47c9"
down_revision: str | Sequence[str] | None = "2b6f0c9d4e71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_subject", sa.String(length=255), nullable=True))
    op.execute("UPDATE users SET auth_subject = 'legacy:' || id::text WHERE auth_subject IS NULL")
    op.execute("UPDATE users SET email = lower(email)")
    op.alter_column("users", "auth_subject", existing_type=sa.String(length=255), nullable=False)
    op.create_unique_constraint("uq_users_auth_subject", "users", ["auth_subject"])
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "categorization_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("pattern", sa.String(length=100), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_from", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "created_from IN ('seed', 'user')",
            name=op.f("ck_categorization_rules_valid_rule_origin"),
        ),
        sa.CheckConstraint(
            "pattern <> '' AND pattern = upper(pattern)",
            name=op.f("ck_categorization_rules_pattern_normalized"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_rule_category_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_categorization_rules_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categorization_rules")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_categorization_rules_id")),
        sa.UniqueConstraint("user_id", "pattern", name="uq_rules_user_pattern"),
    )


def downgrade() -> None:
    op.drop_table("categorization_rules")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.drop_constraint("uq_users_auth_subject", "users", type_="unique")
    op.drop_column("users", "auth_subject")
