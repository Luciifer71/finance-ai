"""Seed two synthetic users with realistic data: ``python scripts/dev.py seed``.

Users: ``user.a@example.test`` and ``user.b@example.test`` (sign in with
``scripts/dev.py token user.a@example.test``). Each gets a bank account, a cash
wallet and a credit card; salary, rent, groceries, food delivery, rides,
subscriptions, bills, ATM withdrawals paired to the wallet, a refunded order,
and budgets for the current month. Everything is invented.

Safe to run again: every row has a deterministic fingerprint, so a second run
adds nothing (``INSERT ... ON CONFLICT DO NOTHING``). Amounts come from a random
generator seeded per user and month, so they are the same on every run.
"""

import hashlib
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import SystemClock
from app.core.security import VerifiedClaims, dev_subject_for
from app.domain.periods import days_in_month
from app.models import BalanceSnapshot, Budget, Category, FinancialAccount, Transaction
from app.services import refunds, transfers
from app.services.categorization import categorize_transactions
from app.services.users import get_or_provision_user

USERS = {"user.a@example.test": Decimal("85000.00"), "user.b@example.test": Decimal("72000.00")}
MONTHS_BACK = 3


@dataclass(frozen=True)
class Row:
    account: str  # "bank" | "cash" | "card"
    day: date
    amount: Decimal
    direction: str
    description: str
    key: str  # unique within one user: makes the fingerprint


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / 100


def _ref(rng: random.Random) -> str:
    return "4027" + "".join(str(rng.randint(0, 9)) for _ in range(8))


def month_rows(email: str, salary: Decimal, first: date, today: date) -> list[Row]:
    rng = random.Random(f"{email}|{first.isoformat()}")  # noqa: S311 - synthetic data, not security
    rows: list[Row] = []
    last_day = days_in_month(first)

    def on(day: int) -> date:
        return first.replace(day=min(day, last_day))

    def add(account: str, day: int, amount: Decimal, direction: str, text: str, key: str) -> None:
        rows.append(Row(account, on(day), amount, direction, text, key))

    add("bank", 1, salary, "credit", "SALARY SYNTHETIC EMPLOYER PVT LTD", "salary")
    add("bank", 3, Decimal("22000.00"), "debit", "NEFT/RENT/SYNTH LANDLORD", "rent")
    add("bank", 5, Decimal("649.00"), "debit", f"UPI/NETFLIX/{_ref(rng)}/SUB", "netflix")
    add("card", 12, Decimal("119.00"), "debit", f"UPI/SPOTIFY/{_ref(rng)}/SUB", "spotify")
    add("bank", 10, _money(rng, 1200, 2200), "debit", "ELECTRICITY BILL BESCOM SYNTH", "power")
    add("bank", 15, Decimal("3000.00"), "debit", "ATM CASH WDL SYNTH BRANCH", "atm")
    for week in range(4):
        add(
            "bank",
            2 + 7 * week,
            _money(rng, 800, 2500),
            "debit",
            f"UPI/BLINKIT/{_ref(rng)}/GROCERY",
            f"grocery{week}",
        )
    for n in range(rng.randint(6, 10)):
        merchant = rng.choice(["SWIGGY", "ZOMATO"])
        add(
            "card",
            rng.randint(1, 28),
            _money(rng, 150, 800),
            "debit",
            f"UPI/{merchant}/{_ref(rng)}/FOOD",
            f"food{n}",
        )
    for n in range(rng.randint(4, 8)):
        merchant = rng.choice(["UBER", "OLA CABS", "RAPIDO"])
        add(
            "bank",
            rng.randint(1, 28),
            _money(rng, 90, 450),
            "debit",
            f"UPI/{merchant}/{_ref(rng)}/RIDE",
            f"ride{n}",
        )
    for n in range(rng.randint(2, 4)):
        add(
            "cash",
            rng.randint(16, 28),
            _money(rng, 20, 300),
            "debit",
            rng.choice(["Chai and snacks", "Vegetable market", "Auto rickshaw"]),
            f"cash{n}",
        )
    return [r for r in rows if r.day <= today]


def _accounts(session: Session, user_id: UUID, last4: str) -> dict[str, UUID]:
    wanted = {
        "bank": ("Synthetic Savings", "bank", last4),
        "cash": ("Wallet cash", "cash", None),
        "card": ("Synthetic Credit Card", "credit", None),
    }
    found: dict[str, UUID] = {}
    for key, (name, kind, digits) in wanted.items():
        account = session.scalars(
            select(FinancialAccount).where(
                FinancialAccount.user_id == user_id, FinancialAccount.name == name
            )
        ).first()
        if account is None:
            account = FinancialAccount(
                user_id=user_id, name=name, account_type=kind, currency="INR", last4=digits
            )
            session.add(account)
            session.flush()
        found[key] = account.id
    return found


def _fingerprint(email: str, row_key: str) -> str:
    return hashlib.sha256(f"seed|{email}|{row_key}".encode()).hexdigest()


def seed_user(session: Session, email: str, salary: Decimal, today: date) -> dict[str, int]:
    user = get_or_provision_user(session, VerifiedClaims(dev_subject_for(email), email))
    accounts = _accounts(session, user.id, "1111" if email.startswith("user.a") else "2222")
    start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for _ in range(MONTHS_BACK - 1):
        start = (start - timedelta(days=1)).replace(day=1)

    opening = start - timedelta(days=1)
    for key, balance in (("bank", "50000.00"), ("cash", "1000.00"), ("card", "0.00")):
        session.execute(
            insert(BalanceSnapshot)
            .values(
                user_id=user.id,
                account_id=accounts[key],
                as_of=opening,
                balance=Decimal(balance),
                source="user_entered",
            )
            .on_conflict_do_nothing(constraint="uq_snapshot_account_date_source")
        )

    rows: list[Row] = []
    month = start
    while month <= today:
        rows += [
            Row(r.account, r.day, r.amount, r.direction, r.description, f"{month:%Y-%m}/{r.key}")
            for r in month_rows(email, salary, month, today)
        ]
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    # One online order in the first month, partly refunded a week later.
    order_day, refund_day = start.replace(day=8), start.replace(day=15)
    rows += [
        Row(
            "bank",
            order_day,
            Decimal("2499.00"),
            "debit",
            "UPI/AMAZON/402799991111/ORDER",
            "amazon-order",
        ),
        Row(
            "bank",
            refund_day,
            Decimal("999.00"),
            "credit",
            "UPI/AMAZON/402799992222/REFUND",
            "amazon-refund",
        ),
    ]

    inserted = (
        session.execute(
            insert(Transaction)
            .values(
                [
                    {
                        "user_id": user.id,
                        "account_id": accounts[r.account],
                        "amount": r.amount,
                        "direction": r.direction,
                        "transaction_type": "expense" if r.direction == "debit" else "income",
                        "description": r.description,
                        "source": "seed",
                        "fingerprint": _fingerprint(email, r.key),
                        "posted_on": r.day,
                    }
                    for r in rows
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[Transaction.account_id, Transaction.fingerprint]
            )
            .returning(Transaction.id)
        )
        .scalars()
        .all()
    )
    session.flush()

    by_fingerprint = {
        tx.fingerprint: tx
        for tx in session.scalars(select(Transaction).where(Transaction.user_id == user.id))
    }
    new_rows = [tx for tx in by_fingerprint.values() if tx.id in set(inserted)]
    categorize_transactions(session, user.id, new_rows)
    session.commit()

    # ATM withdrawals become transfers into the wallet (skipped if already paired).
    for r in rows:
        tx = by_fingerprint[_fingerprint(email, r.key)]
        if r.key.endswith("/atm") and tx.transfer_group_id is None:
            transfers.confirm_cash_withdrawal(session, user.id, tx.id, accounts["cash"])
    order = by_fingerprint[_fingerprint(email, "amazon-order")]
    refund = by_fingerprint[_fingerprint(email, "amazon-refund")]
    if refund.refund_of_id is None:
        refunds.link(session, user.id, refund.id, order.id)

    food = session.scalars(
        select(Category.id).where(Category.user_id == user.id, Category.name == "Food & Dining")
    ).one()
    for category_id, amount in ((food, "6000.00"), (None, "45000.00")):
        session.execute(
            insert(Budget)
            .values(
                user_id=user.id,
                category_id=category_id,
                month=today.replace(day=1),
                amount=Decimal(amount),
                warn_at_percent=80,
            )
            .on_conflict_do_nothing(constraint="uq_budgets_user_category_month")
        )
    session.commit()
    total = session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.user_id == user.id)
    )
    # "added" counts statement-like rows; confirming an ATM withdrawal also adds its cash side.
    return {"transactions_added": len(inserted), "transactions_total": int(total or 0)}


def seed(session: Session, today: date) -> dict[str, dict[str, int]]:
    return {email: seed_user(session, email, salary, today) for email, salary in USERS.items()}


def main() -> int:
    from app.core.config import get_settings
    from app.database import create_db_engine, create_session_factory

    settings = get_settings()
    if settings.app_env == "production":
        print("Refusing to seed a production database.", file=sys.stderr)
        return 1
    engine = create_db_engine(settings.database_url)
    try:
        with create_session_factory(engine)() as session:
            result = seed(session, SystemClock().today())
    finally:
        engine.dispose()
    for email, counts in result.items():
        print(
            f"{email}: {counts['transactions_added']} added, "
            f"{counts['transactions_total']} in total"
        )
    print("Sign in with: python scripts/dev.py token user.a@example.test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
