"""PostgreSQL integration tests using synthetic financial data."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    BalanceSnapshot,
    Category,
    FinancialAccount,
    Transaction,
    TransactionImport,
    User,
)


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
        "direction": "debit",
        "transaction_type": "expense",
        "source": "integration_test",
        "posted_on": date(2026, 11, 5),
        # Real code uses app.domain.fingerprint; any unique 64-char value works here.
        "fingerprint": uuid4().hex * 2,
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


def add_and_expect_rejection(session, row):
    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()


# --- duplicates -------------------------------------------------------------


def test_same_fingerprint_twice_in_one_account_is_rejected(db_session):
    user, account = create_user_and_account(db_session)
    db_session.add(create_transaction(user, account, fingerprint="a" * 64))
    db_session.flush()

    add_and_expect_rejection(db_session, create_transaction(user, account, fingerprint="a" * 64))


def test_same_fingerprint_in_two_accounts_is_allowed(db_session):
    user, account = create_user_and_account(db_session)
    second_account = FinancialAccount(
        user_id=user.id, name="Second", account_type="bank", currency="INR"
    )
    db_session.add(second_account)
    db_session.flush()

    db_session.add(create_transaction(user, account, fingerprint="a" * 64))
    db_session.add(create_transaction(user, second_account, fingerprint="a" * 64))
    db_session.flush()


# --- direction and type -----------------------------------------------------


@pytest.mark.parametrize(
    ("transaction_type", "direction"),
    [("expense", "credit"), ("income", "debit"), ("refund", "debit")],
)
def test_type_must_match_direction(db_session, transaction_type, direction):
    user, account = create_user_and_account(db_session)
    add_and_expect_rejection(
        db_session,
        create_transaction(user, account, transaction_type=transaction_type, direction=direction),
    )


def test_unknown_direction_is_rejected(db_session):
    user, account = create_user_and_account(db_session)
    add_and_expect_rejection(db_session, create_transaction(user, account, direction="out"))


# --- transfers --------------------------------------------------------------


def test_both_sides_of_a_transfer_share_a_group(db_session):
    user, hdfc = create_user_and_account(db_session)
    sbi = FinancialAccount(user_id=user.id, name="SBI", account_type="bank", currency="INR")
    db_session.add(sbi)
    db_session.flush()

    group = uuid4()
    money_out = create_transaction(
        user, hdfc, transaction_type="transfer", direction="debit", transfer_group_id=group
    )
    money_in = create_transaction(
        user, sbi, transaction_type="transfer", direction="credit", transfer_group_id=group
    )
    db_session.add_all([money_out, money_in])
    db_session.flush()

    linked = db_session.query(Transaction).filter_by(transfer_group_id=group).all()
    assert {tx.direction for tx in linked} == {"debit", "credit"}


def test_expense_cannot_join_a_transfer_group(db_session):
    user, account = create_user_and_account(db_session)
    add_and_expect_rejection(
        db_session, create_transaction(user, account, transfer_group_id=uuid4())
    )


# --- refunds ----------------------------------------------------------------


def test_refund_can_point_to_the_original_purchase(db_session):
    user, account = create_user_and_account(db_session)
    purchase = create_transaction(user, account)
    db_session.add(purchase)
    db_session.flush()

    refund = create_transaction(
        user,
        account,
        transaction_type="refund",
        direction="credit",
        refund_of_id=purchase.id,
    )
    db_session.add(refund)
    db_session.flush()


def test_refund_cannot_point_to_another_users_purchase(db_session):
    user_a, account_a = create_user_and_account(db_session)
    user_b, account_b = create_user_and_account(db_session)
    purchase_b = create_transaction(user_b, account_b)
    db_session.add(purchase_b)
    db_session.flush()

    add_and_expect_rejection(
        db_session,
        create_transaction(
            user_a,
            account_a,
            transaction_type="refund",
            direction="credit",
            refund_of_id=purchase_b.id,
        ),
    )


def test_only_refunds_can_link_to_a_purchase(db_session):
    user, account = create_user_and_account(db_session)
    purchase = create_transaction(user, account)
    db_session.add(purchase)
    db_session.flush()

    add_and_expect_rejection(
        db_session, create_transaction(user, account, refund_of_id=purchase.id)
    )


# --- categories -------------------------------------------------------------


def test_cannot_use_another_users_category(db_session):
    user_a, account_a = create_user_and_account(db_session)
    user_b, _ = create_user_and_account(db_session)
    food_b = Category(user_id=user_b.id, name="Food", kind="expense")
    db_session.add(food_b)
    db_session.flush()

    add_and_expect_rejection(
        db_session, create_transaction(user_a, account_a, category_id=food_b.id)
    )


def test_category_names_are_unique_per_user_only(db_session):
    user_a, _ = create_user_and_account(db_session)
    user_b, _ = create_user_and_account(db_session)
    db_session.add_all(
        [
            Category(user_id=user_a.id, name="Food", kind="expense"),
            Category(user_id=user_b.id, name="Food", kind="expense"),
        ]
    )
    db_session.flush()

    add_and_expect_rejection(db_session, Category(user_id=user_a.id, name="Food", kind="expense"))


# --- imports ----------------------------------------------------------------


def make_import(user, account, **overrides):
    values = {
        "user_id": user.id,
        "account_id": account.id,
        "source": "integration_test",
        "file_sha256": "f" * 64,
    }
    values.update(overrides)
    return TransactionImport(**values)


def test_same_file_cannot_be_imported_twice_into_one_account(db_session):
    user, account = create_user_and_account(db_session)
    db_session.add(make_import(user, account))
    db_session.flush()

    add_and_expect_rejection(db_session, make_import(user, account))


def test_import_cannot_target_another_users_account(db_session):
    user_a, _ = create_user_and_account(db_session)
    _, account_b = create_user_and_account(db_session)
    add_and_expect_rejection(db_session, make_import(user_a, account_b))


def test_row_counts_cannot_exceed_total(db_session):
    user, account = create_user_and_account(db_session)
    add_and_expect_rejection(db_session, make_import(user, account, rows_total=2, rows_imported=3))


# --- balance snapshots ------------------------------------------------------


def test_opening_balance_can_be_negative(db_session):
    user, account = create_user_and_account(db_session)
    db_session.add(
        BalanceSnapshot(
            user_id=user.id,
            account_id=account.id,
            as_of=date(2026, 11, 1),
            balance=Decimal("-1500.00"),
            source="user_entered",
        )
    )
    db_session.flush()


def test_statement_balance_must_come_from_an_import(db_session):
    user, account = create_user_and_account(db_session)
    add_and_expect_rejection(
        db_session,
        BalanceSnapshot(
            user_id=user.id,
            account_id=account.id,
            as_of=date(2026, 11, 1),
            balance=Decimal("1000.00"),
            source="statement",
        ),
    )
