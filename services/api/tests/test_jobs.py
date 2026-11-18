"""M5: job runner and rule-based categorization (handoff sections 9 and 10)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import FixedClock
from app.jobs import runner
from app.jobs.handlers import HANDLERS, handle_categorize_import
from app.models import Category, Job, Transaction, TransactionEvent
from app.services.categorization import Rule, create_user_rule, match_rule
from tests.conftest import ApiUser
from tests.factories import add_account

FIXTURES = Path(__file__).parent / "fixtures" / "statements"


def scope_for(session: Session):
    @contextmanager
    def scope() -> Iterator[Session]:
        yield session  # the test's rollback-only session; never closed here

    return scope


def import_clean(client: TestClient, user: ApiUser, account_id: object) -> dict:
    preview = client.post(
        "/api/v1/imports",
        files={"file": ("s.csv", (FIXTURES / "clean_12_rows.csv").read_bytes(), "text/csv")},
        data={"account_id": str(account_id), "profile_id": "generic_indian_bank_v1"},
        headers=user.headers,
    ).json()
    return client.post(f"/api/v1/imports/{preview['id']}/commit", headers=user.headers).json()


def categories_by_description(session: Session, user_id: uuid.UUID) -> dict[str, str | None]:
    rows = session.execute(
        select(Transaction.description, Category.name)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(Transaction.user_id == user_id)
    ).all()
    return dict(rows)


# --- categorization through the worker --------------------------------------------------------


def test_worker_categorizes_an_import_with_seed_rules(
    client: TestClient, user_a: ApiUser, db_session: Session, clock: FixedClock
):
    account = add_account(db_session, user_a.id)
    result = import_clean(client, user_a, account.id)

    ran = runner.process_available(scope_for(db_session), HANDLERS, "w1", clock)

    assert ran == 1
    cats = categories_by_description(db_session, user_a.id)
    assert cats["UPI/SWIGGY/402711112222/FOOD"] == "Food & Dining"
    assert cats["UPI/BLINKIT/402711113333/GROCERY"] == "Groceries"
    assert cats["UPI/UBER/402711114444/RIDE"] == "Transport"
    assert cats["UPI/NETFLIX/402711115555/SUB"] == "Subscriptions"
    assert cats["UPI/AMAZON/402711116666/ORDER"] == "Shopping"
    assert cats["UPI/ZOMATO/402711119999/FOOD"] == "Food & Dining"
    # A credit is income: the expense-kind Shopping rule does not fit it.
    assert cats["UPI/AMAZON/402711117777/REFUND"] is None
    assert cats["SALARY OCT ACME SYNTHETIC LTD"] is None  # no rule: left for the user

    job = db_session.get(Job, uuid.UUID(result["categorize_job_id"]))
    assert (job.status, job.attempts) == ("succeeded", 1)
    rule_events = db_session.scalars(
        select(TransactionEvent).where(TransactionEvent.actor == "rule")
    ).all()
    assert len(rule_events) == 6
    assert {e.event_type for e in rule_events} == {"categorized_by_rule"}
    response = client.get(f"/api/v1/jobs/{job.id}", headers=user_a.headers)
    assert response.json()["status"] == "succeeded"


def test_rerunning_a_succeeded_job_is_a_no_op(
    client: TestClient, user_a: ApiUser, db_session: Session, clock: FixedClock
):
    account = add_account(db_session, user_a.id)
    result = import_clean(client, user_a, account.id)
    runner.process_available(scope_for(db_session), HANDLERS, "w1", clock)
    events_before = len(db_session.scalars(select(TransactionEvent)).all())

    # The runner never picks it up again ...
    assert runner.run_one(scope_for(db_session), HANDLERS, "w1", clock) is None
    # ... and even calling the handler directly changes nothing.
    handle_categorize_import(
        db_session, db_session.get(Job, uuid.UUID(result["categorize_job_id"]))
    )
    assert len(db_session.scalars(select(TransactionEvent)).all()) == events_before


def test_user_categorized_rows_are_never_overwritten_by_rules(
    client: TestClient, user_a: ApiUser, db_session: Session, clock: FixedClock
):
    account = add_account(db_session, user_a.id)
    import_clean(client, user_a, account.id)
    swiggy = db_session.scalars(
        select(Transaction).where(Transaction.description == "UPI/SWIGGY/402711112222/FOOD")
    ).one()
    groceries = next(
        c["id"]
        for c in client.get("/api/v1/categories", headers=user_a.headers).json()["items"]
        if c["name"] == "Groceries"
    )
    client.patch(
        f"/api/v1/transactions/{swiggy.id}", json={"category_id": groceries}, headers=user_a.headers
    )

    runner.process_available(scope_for(db_session), HANDLERS, "w1", clock)

    db_session.refresh(swiggy)
    assert (str(swiggy.category_id), swiggy.category_source) == (groceries, "user")


def test_user_rule_from_an_edit_beats_the_seed_rule(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    tx = client.post(
        "/api/v1/transactions",
        json={
            "account_id": str(account.id),
            "posted_on": "2026-11-01",
            "amount": "300.00",
            "direction": "debit",
            "description": "UPI/SWIGGY/402700000001/INSTAMART",
        },
        headers=user_a.headers,
    ).json()
    groceries = next(
        c["id"]
        for c in client.get("/api/v1/categories", headers=user_a.headers).json()["items"]
        if c["name"] == "Groceries"
    )
    response = client.patch(
        f"/api/v1/transactions/{tx['id']}",
        json={"category_id": groceries, "create_rule": True},
        headers=user_a.headers,
    )
    assert response.status_code == 200

    from app.services.categorization import active_rules

    rules = active_rules(db_session, user_a.id)
    assert rules[0].pattern == "SWIGGY INSTAMART" and rules[0].from_user
    # A later "SWIGGY INSTAMART" purchase matches the seed SWIGGY rule too; the user rule wins.
    best = match_rule(rules, "UPI/SWIGGY/402700000002/INSTAMART", "expense")
    assert best is not None and str(best.category_id) == groceries
    # Plain Swiggy food orders still follow the seed rule.
    food = match_rule(rules, "UPI/SWIGGY/402700000003/FOOD", "expense")
    assert food is not None and not food.from_user


def test_create_rule_needs_a_category_and_a_merchant(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)

    def make(description: str) -> str:
        return client.post(
            "/api/v1/transactions",
            json={
                "account_id": str(account.id),
                "posted_on": "2026-11-01",
                "amount": "1.00",
                "direction": "debit",
                "description": description,
            },
            headers=user_a.headers,
        ).json()["id"]

    fuel = next(
        c["id"]
        for c in client.get("/api/v1/categories", headers=user_a.headers).json()["items"]
        if c["name"] == "Fuel"
    )
    no_category = client.patch(
        f"/api/v1/transactions/{make('HPCL PUMP')}",
        json={"create_rule": True},
        headers=user_a.headers,
    )
    assert no_category.json()["code"] == "rule.category_required"
    no_merchant = client.patch(
        f"/api/v1/transactions/{make('402711112222')}",
        json={"category_id": fuel, "create_rule": True},
        headers=user_a.headers,
    )
    assert no_merchant.json()["code"] == "rule.no_merchant"


def test_rule_matching_prefers_user_then_priority_then_longer_pattern():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rules = sorted(
        [
            Rule("OLA", a, "expense", 100, False),
            Rule("OLA CABS", b, "expense", 100, False),
            Rule("CABS", c, "expense", 10, True),
        ],
        key=lambda r: (not r.from_user, r.priority, -len(r.pattern), r.pattern),
    )
    assert match_rule(rules, "UPI/OLA CABS/1234567/RIDE", "expense").category_id == c
    assert match_rule(rules[1:], "UPI/OLA CABS/1234567/RIDE", "expense").category_id == b
    assert match_rule(rules, "UPI/COCA COLA/1234567", "expense") is None  # whole words only
    assert match_rule(rules, "OLA CABS", "transfer") is None


def test_create_user_rule_upserts(db_session: Session, user_a: ApiUser):
    groceries = db_session.scalars(
        select(Category).where(Category.user_id == user_a.id, Category.name == "Groceries")
    ).one()
    assert create_user_rule(db_session, user_a.id, "UPI/SWIGGY/1234567", groceries.id) == "SWIGGY"
    from app.models import CategorizationRule

    rule = db_session.scalars(
        select(CategorizationRule).where(
            CategorizationRule.user_id == user_a.id, CategorizationRule.pattern == "SWIGGY"
        )
    ).one()
    assert (rule.created_from, rule.category_id, rule.priority) == ("user", groceries.id, 10)


# --- failure handling -------------------------------------------------------------------------


def test_failing_handler_ends_dead_and_leaves_everything_usable(
    client: TestClient,
    user_a: ApiUser,
    db_session: Session,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
):
    def always_fails(session: Session, job: Job) -> None:
        raise RuntimeError("simulated categorizer outage")

    handlers = {**HANDLERS, "categorize_import": always_fails}
    account = add_account(db_session, user_a.id)
    result = import_clean(client, user_a, account.id)
    job_id = uuid.UUID(result["categorize_job_id"])

    now = clock.now()
    statuses = []
    for _attempt in range(5):
        assert runner.run_one(scope_for(db_session), handlers, "w1", FixedClock(now)) == job_id
        job = db_session.get(Job, job_id)
        statuses.append((job.status, job.attempts))
        now += timedelta(minutes=16)  # past any backoff (cap 15 minutes)

    assert statuses == [("failed", 1), ("failed", 2), ("failed", 3), ("failed", 4), ("dead", 5)]
    assert job.last_error == "RuntimeError"  # the type only, never the message
    assert runner.run_one(scope_for(db_session), handlers, "w1", FixedClock(now)) is None
    # The import and the ledger are unaffected.
    detail = client.get(f"/api/v1/imports/{result['id']}", headers=user_a.headers).json()
    assert detail["status"] == "completed"
    assert len(client.get("/api/v1/transactions", headers=user_a.headers).json()["items"]) == 12
    balance = client.get(f"/api/v1/accounts/{account.id}/balance", headers=user_a.headers)
    assert balance.json()["balance"] == "34125.00"
    assert client.get(f"/api/v1/jobs/{job_id}", headers=user_a.headers).json()["status"] == "dead"


def test_failed_job_waits_for_its_backoff(db_session: Session, clock: FixedClock):
    job = Job(
        kind="explodes",
        payload={},
        status="queued",
        attempts=0,
        max_attempts=5,
        run_after=clock.now(),
        idempotency_key=f"t-{uuid.uuid4()}",
    )
    db_session.add(job)
    db_session.flush()
    handlers = {"explodes": lambda s, j: (_ for _ in ()).throw(ValueError())}

    runner.run_one(scope_for(db_session), handlers, "w1", clock, rand=lambda: 1.0)
    db_session.refresh(job)
    # attempt 1: 2^1 = 2 s, jitter factor 0.75 + 0.25 * 1.0 = 1.0 -> 2 s
    assert job.status == "failed"
    assert job.run_after == clock.now() + timedelta(seconds=2)
    assert runner.run_one(scope_for(db_session), handlers, "w1", clock) is None  # not yet
    later = FixedClock(clock.now() + timedelta(seconds=2))
    assert runner.run_one(scope_for(db_session), handlers, "w1", later) == job.id


def test_unknown_job_kind_fails_with_a_lookup_error(db_session: Session, clock: FixedClock):
    job = Job(
        kind="no_such_kind",
        payload={},
        status="queued",
        attempts=0,
        max_attempts=1,
        run_after=clock.now(),
        idempotency_key=f"t-{uuid.uuid4()}",
    )
    db_session.add(job)
    db_session.flush()
    runner.run_one(scope_for(db_session), {}, "w1", clock)
    db_session.refresh(job)
    assert (job.status, job.last_error) == ("dead", "LookupError")


@pytest.mark.parametrize(
    ("attempts", "rand", "seconds"),
    [(1, 0.0, 1.5), (1, 1.0, 2.0), (3, 0.0, 6.0), (10, 1.0, 900.0), (20, 0.0, 675.0)],
)
def test_backoff(attempts: int, rand: float, seconds: float):
    # 2^attempts capped at 900, times (0.75 + 0.25 * rand)
    assert runner.backoff_seconds(attempts, lambda: rand) == seconds


def test_stale_running_jobs_are_requeued_or_dead(db_session: Session, clock: FixedClock):
    old = clock.now() - timedelta(minutes=11)
    retry = Job(
        kind="k",
        payload={},
        status="running",
        attempts=1,
        max_attempts=5,
        locked_by="crashed",
        locked_at=old,
        idempotency_key=f"t-{uuid.uuid4()}",
    )
    spent = Job(
        kind="k",
        payload={},
        status="running",
        attempts=5,
        max_attempts=5,
        locked_by="crashed",
        locked_at=old,
        idempotency_key=f"t-{uuid.uuid4()}",
    )
    fresh = Job(
        kind="k",
        payload={},
        status="running",
        attempts=1,
        max_attempts=5,
        locked_by="alive",
        locked_at=clock.now() - timedelta(minutes=5),
        idempotency_key=f"t-{uuid.uuid4()}",
    )
    db_session.add_all([retry, spent, fresh])
    db_session.flush()

    runner.release_ready(db_session, clock.now())
    for job in (retry, spent, fresh):
        db_session.refresh(job)

    assert (retry.status, retry.locked_by) == ("queued", None)
    assert spent.status == "dead"
    assert fresh.status == "running"


def test_two_workers_never_claim_the_same_job(engine: Engine, clock: FixedClock):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    keys = [f"skip-locked-{uuid.uuid4()}" for _ in range(2)]
    with factory() as setup:
        setup.add_all(
            [
                Job(
                    kind="k",
                    payload={},
                    status="queued",
                    attempts=0,
                    max_attempts=5,
                    run_after=clock.now(),
                    idempotency_key=k,
                )
                for k in keys
            ]
        )
        setup.commit()
    first, second, third = factory(), factory(), factory()
    try:
        job_1 = runner.claim_next(first, "worker-1", clock.now())  # lock held, not committed
        job_2 = runner.claim_next(second, "worker-2", clock.now())
        job_3 = runner.claim_next(third, "worker-3", clock.now())
        assert job_1 is not None and job_2 is not None
        assert job_1.id != job_2.id
        assert job_3 is None
    finally:
        for session in (first, second, third):
            session.rollback()
            session.close()
        with factory() as cleanup:
            cleanup.execute(delete(Job).where(Job.idempotency_key.in_(keys)))
            cleanup.commit()


def test_worker_command_drains_and_exits(monkeypatch: pytest.MonkeyPatch, test_database_url: str):
    from app import worker
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    calls = []
    monkeypatch.setattr(worker, "process_available", lambda *args, **kwargs: calls.append(1) or 0)
    try:
        assert worker.main(["--once"]) == 0
    finally:
        get_settings.cache_clear()
    assert calls == [1]
