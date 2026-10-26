"""Core database models for Finance AI."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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


class TransactionImport(Base):
    """Track ingestion batches and their processing lifecycle."""

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
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="valid_import_status",
        ),
        Index("ix_transaction_imports_user", "user_id"),
    )


class Transaction(Base):
    """A user-owned financial transaction."""

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
    destination_account_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    import_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="manual",
    )
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_tx_account_owner",
        ),
        ForeignKeyConstraint(
            ["destination_account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            name="fk_tx_destination_owner",
        ),
        ForeignKeyConstraint(
            ["import_id", "user_id"],
            ["transaction_imports.id", "transaction_imports.user_id"],
            name="fk_tx_import_owner",
        ),
        UniqueConstraint(
            "user_id",
            "account_id",
            "source",
            "external_id",
            name="uq_tx_external_reference",
        ),
        CheckConstraint(
            "amount > 0",
            name="positive_amount",
        ),
        CheckConstraint(
            "transaction_type IN ('income', 'expense', 'transfer')",
            name="valid_transaction_type",
        ),
        CheckConstraint(
            "(transaction_type = 'transfer' AND "
            "destination_account_id IS NOT NULL AND "
            "destination_account_id <> account_id) OR "
            "(transaction_type <> 'transfer' AND "
            "destination_account_id IS NULL)",
            name="valid_transfer_accounts",
        ),
        Index(
            "ix_transactions_user_occurred",
            "user_id",
            "occurred_at",
        ),
    )
