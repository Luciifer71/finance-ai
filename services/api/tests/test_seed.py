"""M7: the seed script creates realistic data for users A and B and is idempotent."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, Transaction, User
from app.tools.seed import seed

TODAY = date(2026, 11, 18)


def counts(session: Session, user_id) -> tuple[int, int, int, int]:
    def count(*where) -> int:
        return session.scalar(select(func.count()).select_from(Transaction).where(*where))

    mine = Transaction.user_id == user_id
    return (
        count(mine),
        count(mine, Transaction.transaction_type == "transfer"),
        count(mine, Transaction.transaction_type == "refund"),
        count(mine, Transaction.category_source == "rule"),
    )


def test_seed_twice_adds_nothing_the_second_time(db_session: Session):
    first = seed(db_session, TODAY)
    users = {
        u.email: u.id
        for u in db_session.scalars(select(User).where(User.email.like("user.%@example.test")))
    }
    before = {email: counts(db_session, uid) for email, uid in users.items()}

    second = seed(db_session, TODAY)

    assert {e: c["transactions_added"] for e, c in second.items()} == {
        "user.a@example.test": 0,
        "user.b@example.test": 0,
    }
    assert {email: counts(db_session, uid) for email, uid in users.items()} == before
    for email, result in first.items():
        assert result["transactions_added"] > 50, email  # Aug-Oct full months + 18 days of Nov
        total, transfer_rows, refund_rows, rule_rows = before[email]
        # 4 ATM withdrawals (15 Aug, Sep, Oct, Nov) -> 4 pairs = 8 transfer rows
        assert transfer_rows == 8
        assert refund_rows == 1
        assert rule_rows > 20
        assert total == result["transactions_total"] == result["transactions_added"] + 4
    budgets = db_session.scalar(
        select(func.count()).select_from(Budget).where(Budget.user_id.in_(users.values()))
    )
    assert budgets == 4  # Food & Dining + all spending, for each user


def test_seed_dates_never_go_past_today(db_session: Session):
    seed(db_session, TODAY)
    latest = db_session.scalar(select(func.max(Transaction.posted_on)))
    earliest = db_session.scalar(select(func.min(Transaction.posted_on)))
    assert latest <= TODAY
    assert earliest == date(2026, 8, 1)
