"""Core database models for Finance AI."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    """Application identity.

    Sign-in happens at Supabase Auth; ``auth_subject`` is the token's ``sub``
    claim and is how a token is matched to this row. Email is stored lower-case
    and is unique ignoring case.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("auth_subject", name="uq_users_auth_subject"),
        Index("uq_users_email_lower", func.lower(email), unique=True),
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
    # Last 4 digits of the account number, optional; helps spot self-transfers.
    last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # Archived accounts keep their history but are hidden by default. Never deleted.
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
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
        CheckConstraint("last4 IS NULL OR last4 ~ '^[0-9]{4}$'", name="valid_last4"),
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
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
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
    # Which mapping profile parsed the file, and what the preview found.
    # The file itself is never stored.
    profile_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    closing_balance_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
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
            "status IN ('pending', 'previewed', 'processing', 'completed', 'failed', 'cancelled')",
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
    # Which line of the import's file this row came from (imported rows only).
    import_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # --- user-editable fields (every change writes a transaction_events row) ---
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Who chose the category: a rule, the user, the system, or nobody yet.
    category_source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="none", server_default="none"
    )
    # Hidden from reports; the fact itself stays (deleting is not supported).
    is_excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
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
        CheckConstraint(
            "category_source IN ('rule', 'user', 'system', 'none')",
            name="valid_category_source",
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


class CategorizationRule(Base):
    """Maps a merchant word (e.g. SWIGGY) to one of the user's categories.

    ``seed`` rules are created at sign-up; ``user`` rules come from the user
    re-categorising a transaction and beat seed rules.
    """

    __tablename__ = "categorization_rules"

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
    pattern: Mapped[str] = mapped_column(String(100), nullable=False)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_from: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_rule_category_owner",
        ),
        UniqueConstraint("user_id", "pattern", name="uq_rules_user_pattern"),
        CheckConstraint("created_from IN ('seed', 'user')", name="valid_rule_origin"),
        CheckConstraint("pattern <> '' AND pattern = upper(pattern)", name="pattern_normalized"),
    )


class ImportRow(Base):
    """One parsed data row of an uploaded statement, shown in the preview.

    Only parsed fields are kept, never the raw line. ``raw_hash`` lets support
    tell whether two files had the same line without storing it.
    """

    __tablename__ = "import_rows"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    import_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    posted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(6), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["import_id", "user_id"],
            ["transaction_imports.id", "transaction_imports.user_id"],
            name="fk_import_row_import_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("import_id", "row_number", name="uq_import_rows_import_row"),
        CheckConstraint(
            "status IN ('valid', 'invalid', 'duplicate_in_file', 'already_imported')",
            name="valid_row_status",
        ),
        CheckConstraint(
            "status = 'invalid' OR (posted_on IS NOT NULL AND amount > 0 "
            "AND direction IN ('debit', 'credit') AND fingerprint IS NOT NULL)",
            name="parsed_rows_complete",
        ),
    )


class Job(Base):
    """A unit of background work in the PostgreSQL outbox (handoff section 9).

    Enqueued in the same database transaction as the change that needs it, so a
    committed import always has its categorization job, and a rolled-back one never does.
    """

    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'dead')",
            name="valid_job_status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="valid_attempts"),
        # The worker's "next job to run" query.
        Index("ix_jobs_status_run_after", "status", "run_after"),
    )


class AccessAudit(Base):
    """Who imported or exported data, or failed to sign in repeatedly.

    Never holds tokens, amounts, descriptions or file contents.
    """

    __tablename__ = "access_audit"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_access_audit_user_created", "user_id", "created_at"),)


class TransactionEvent(Base):
    """Append-only history of every change to a transaction's editable fields.

    Written in the same database transaction as the change. A trigger rejects
    any UPDATE or DELETE, so history cannot be rewritten.
    """

    __tablename__ = "transaction_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # Strictly increasing order of writing; created_at is the same for every event of
    # one database transaction, so it cannot order them.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name="fk_event_transaction_owner",
        ),
        CheckConstraint("actor IN ('user', 'system', 'rule')", name="valid_actor"),
        UniqueConstraint("seq", name="uq_transaction_events_seq"),
        Index("ix_transaction_events_tx_seq", "transaction_id", "seq"),
    )


class Budget(Base):
    """A spending limit for one month, for one category or (category NULL) all spending."""

    __tablename__ = "budgets"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    category_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # The first day of the budget's month (the API speaks "YYYY-MM").
    month: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    warn_at_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80, server_default="80"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_budget_category_owner",
        ),
        # One budget per (user, category, month); "all spending" (NULL) counts as one value.
        UniqueConstraint(
            "user_id",
            "category_id",
            "month",
            name="uq_budgets_user_category_month",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("warn_at_percent BETWEEN 1 AND 100", name="valid_warn_percent"),
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="month_is_first_day"),
    )
