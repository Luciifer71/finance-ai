"""PostgreSQL integration tests using synthetic financial data."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import FinancialAccount, Transaction, User


@pytest.fixture
def db_session():
    """Use only the isolated test database and roll back all writes."""
    database_url = os.environ.get("TEST_DATABASE_URL")

    if not database_url:
        pytest.fail("TEST_DATABASE_URL must be configured explicitly.")

    url = make_url(database_url)

    if (
        url.drivername != "postgresql+psycopg"
        or url.database != "finance_test"
        or url.host not in ("127.0.0.1", "localhost")
        or url.port != 5432
    ):
        pytest.fail("Refusing to run against an unexpected database.")

    if database_url == os.environ.get("DATABASE_URL"):
        pytest.fail("Test database must differ from development database.")

    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            outer_transaction = connection.begin()

            session = Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            )

            try:
                yield session
            finally:
                session.close()
                if outer_transaction.is_active:
                    outer_transaction.rollback()
    finally:
        engine.dispose()


def create_user_and_account(session, email=None):
    """Create a user first, then their financial account."""
    user = User(
        id=uuid4(),
        email=email or f"{uuid4()}@example.test",
    )

    # Persist the user before inserting the dependent account.
    session.add(user)
    session.flush()

    account = FinancialAccount(
        id=uuid4(),
        user_id=user.id,
        name="Synthetic Test Account",
        account_type="bank",
        currency="INR",
    )

    session.add(account)
    session.flush()

    return user, account


def create_transaction(user, account, **overrides):
    values = {
        "id": uuid4(),
        "user_id": user.id,
        "account_id": account.id,
        "amount": Decimal("250.00"),
        "transaction_type": "expense",
        "source": "integration_test",
        "occurred_at": datetime.now(UTC),
    }

    values.update(overrides)
    return Transaction(**values)


def test_valid_transaction_is_inserted(db_session):
    user, account = create_user_and_account(db_session)
    transaction = create_transaction(user, account)

    db_session.add(transaction)
    db_session.flush()

    stored = db_session.get(Transaction, transaction.id)

    assert stored is not None
    assert stored.amount == Decimal("250.00")
    assert stored.user_id == user.id


def test_cannot_use_another_users_account(db_session):
    user_a, _ = create_user_and_account(db_session)
    _, account_b = create_user_and_account(db_session)

    transaction = create_transaction(user_a, account_b)
    db_session.add(transaction)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_external_reference_is_rejected(db_session):
    user, account = create_user_and_account(db_session)

    first = create_transaction(
        user,
        account,
        external_id="test-payment-001",
    )

    duplicate = create_transaction(
        user,
        account,
        external_id="test-payment-001",
    )

    db_session.add(first)
    db_session.flush()

    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_negative_transaction_amount_is_rejected(db_session):
    user, account = create_user_and_account(db_session)

    transaction = create_transaction(
        user,
        account,
        amount=Decimal("-100.00"),
    )

    db_session.add(transaction)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_transfer_to_same_account_is_rejected(db_session):
    user, account = create_user_and_account(db_session)

    transaction = create_transaction(
        user,
        account,
        transaction_type="transfer",
        destination_account_id=account.id,
    )

    db_session.add(transaction)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_transfer_to_another_users_account_is_rejected(db_session):
    user_a, account_a = create_user_and_account(db_session)
    _, account_b = create_user_and_account(db_session)

    transaction = create_transaction(
        user_a,
        account_a,
        transaction_type="transfer",
        destination_account_id=account_b.id,
    )

    db_session.add(transaction)

    with pytest.raises(IntegrityError):
        db_session.flush()
