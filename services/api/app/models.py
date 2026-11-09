"""Core database models for Finance AI."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Money is stored as an exact decimal with 2 places (rupees and paise).
# Never use float for money: 0.1 + 0.2 != 0.3 in floating point.
Money = Numeric(18, 2)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    """Application identity; authentication will be separate."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FinancialAccount(Base):
    """Bank, cash, or other user-owned financial account."""

    __tablename__ = "financial_accounts"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        CheckConstraint(
            "account_type IN ('bank', 'cash', 'credit', 'wallet')",
            name="valid_account_type",
        ),
        CheckConstraint(
            "currency = 'INR'",
            name="supported_currency",
        ),
        Index("ix_financial_accounts_user", "user_id"),
    )


class Category(Base):
    """A user's own spending or income category, such as Food or Salary."""

    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
        CheckConstraint(
            "kind IN ('expense', 'income')",
            name="valid_category_kind",
        ),
    )


class TransactionImport(Base):
    """One uploaded statement file and what happened to its rows."""

    __tablename__ = "transaction_imports"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_import_account_owner",
        ),
        # The same file uploaded twice for the same account is one import.
        UniqueConstraint("account_id", "file_sha256", name="uq_import_account_file"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="valid_import_status",
        ),
        CheckConstraint(
            "rows_total >= 0 AND rows_imported >= 0 AND rows_skipped >= 0 "
            "AND rows_failed >= 0 "
            "AND rows_imported + rows_skipped + rows_failed <= rows_total",
            name="valid_row_counts",
        ),
        Index("ix_transaction_imports_user", "user_id"),
    )


class Transaction(Base):
    """One line of money moving in or out of one account.

    ``direction`` is the bank's fact (money left or entered this account).
    ``transaction_type`` is what that movement means for reports.
    """

    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    import_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Money,
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="manual",
    )
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # The calendar date printed on the statement. Reports group by this.
    posted_on: Mapped[date] = mapped_column(Date, nullable=False)
    # The exact moment, only when a source provides one (UPI apps sometimes do).
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Both sides of a transfer between the user's own accounts share this id.
    transfer_group_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    # For a refund: the original purchase it reverses, once matched.
    refund_of_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_tx_account_owner",
        ),
        ForeignKeyConstraint(
            ["import_id", "user_id"],
            ["transaction_imports.id", "transaction_imports.user_id"],
            name="fk_tx_import_owner",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_tx_category_owner",
        ),
        ForeignKeyConstraint(
            ["refund_of_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name="fk_tx_refund_owner",
        ),
        UniqueConstraint(
            "user_id",
            "account_id",
            "source",
            "external_id",
            name="uq_tx_external_reference",
        ),
        UniqueConstraint("account_id", "fingerprint", name="uq_tx_account_fingerprint"),
        CheckConstraint(
            "amount > 0",
            name="positive_amount",
        ),
        CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="valid_direction",
        ),
        CheckConstraint(
            "transaction_type IN ('income', 'expense', 'transfer', 'refund')",
            name="valid_transaction_type",
        ),
        CheckConstraint(
            "(transaction_type = 'expense' AND direction = 'debit') OR "
            "(transaction_type IN ('income', 'refund') AND direction = 'credit') OR "
            "transaction_type = 'transfer'",
            name="type_matches_direction",
        ),
        CheckConstraint(
            "transfer_group_id IS NULL OR transaction_type = 'transfer'",
            name="transfer_group_only_on_transfers",
        ),
        CheckConstraint(
            "refund_of_id IS NULL OR (transaction_type = 'refund' AND refund_of_id <> id)",
            name="refund_link_only_on_refunds",
        ),
        Index("ix_transactions_user_posted", "user_id", "posted_on"),
        Index("ix_transactions_account", "account_id"),
        Index("ix_transactions_transfer_group", "transfer_group_id"),
    )


class BalanceSnapshot(Base):
    """A photo of an account's balance on a date.

    ``statement`` snapshots come from a bank statement and can make a balance
    "verified". ``user_entered`` snapshots (such as an opening balance) are
    always shown as estimates. Whether today's balance is verified is
    calculated, not stored, so it can never go stale.
    """

    __tablename__ = "balance_snapshots"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    import_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    # Can be negative, for example a credit card or an overdraft.
    balance: Mapped[Decimal] = mapped_column(Money, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_snapshot_account_owner",
        ),
        ForeignKeyConstraint(
            ["import_id", "user_id"],
            ["transaction_imports.id", "transaction_imports.user_id"],
            name="fk_snapshot_import_owner",
        ),
        UniqueConstraint(
            "account_id",
            "as_of",
            "source",
            name="uq_snapshot_account_date_source",
        ),
        CheckConstraint(
            "source IN ('statement', 'user_entered')",
            name="valid_snapshot_source",
        ),
        CheckConstraint(
            "source <> 'statement' OR import_id IS NOT NULL",
            name="statement_snapshot_has_import",
        ),
    )
