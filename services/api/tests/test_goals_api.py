"""M8: goals, wishlist, history, projections and the purchase scenario (handoff 6.9).

Clock: 18 Nov 2026 (India). Values are worked out by hand in the comments.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import (
    AccessAudit,
    Budget,
    Goal,
    GoalEvent,
    Job,
    Transaction,
    TransactionEvent,
)
from tests.conftest import ApiUser
from tests.factories import add_account, add_tx


def create_goal(client: TestClient, user: ApiUser, **body: object) -> dict:
    payload = {"name": "New phone", "kind": "wishlist", "target_amount": "45000.00"}
    payload.update(body)
    response = client.post("/api/v1/goals", json=payload, headers=user.headers)
    assert response.status_code == 201, response.text
    return response.json()


def event(client: TestClient, user: ApiUser, goal_id: str, **body: object):
    return client.post(f"/api/v1/goals/{goal_id}/events", json=body, headers=user.headers)


def goal(client: TestClient, user: ApiUser, goal_id: str) -> dict:
    return client.get(f"/api/v1/goals/{goal_id}", headers=user.headers).json()


def test_create_goal_records_a_created_event(client: TestClient, user_a: ApiUser):
    body = create_goal(
        client, user_a, item_url="https://example.com/phone", priority=1, target_date="2027-05-18"
    )
    assert (body["saved"], body["remaining"], body["status"]) == ("0.00", "45000.00", "active")
    (created,) = body["events"]
    assert (created["event_type"], created["actor"]) == ("created", "user")
    assert created["after"]["target_amount"] == "45000.00"
    assert created["after"]["item_url"] == "https://example.com/phone"


@pytest.mark.parametrize(
    "bad",
    [
        {"item_url": "ftp://example.com/x"},
        {"item_url": "javascript:alert(1)"},
        {"target_amount": "0"},
        {"target_amount": 100},
        {"priority": 6},
        {"kind": "loan"},
        {"name": ""},
    ],
)
def test_invalid_goals_are_rejected(client: TestClient, user_a: ApiUser, bad: dict):
    payload = {"name": "X", "kind": "savings", "target_amount": "100.00", **bad}
    assert client.post("/api/v1/goals", json=payload, headers=user_a.headers).status_code == 422


def test_contributions_withdrawals_and_the_zero_floor(client: TestClient, user_a: ApiUser):
    goal_id = create_goal(client, user_a)["id"]
    assert event(
        client, user_a, goal_id, event_type="contribution", amount="10000"
    ).status_code == (201)
    assert event(
        client, user_a, goal_id, event_type="contribution", amount="2500.50"
    ).status_code == (201)
    # saved 10000 + 2500.50 = 12500.50; withdrawing 12500.51 (one paisa more) is rejected
    rejected = event(client, user_a, goal_id, event_type="withdrawal", amount="12500.51")
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "goal.withdrawal_exceeds_saved"
    assert rejected.json()["saved"] == "12500.50"
    # withdrawing exactly what is saved is allowed and leaves 0.00
    exact = event(client, user_a, goal_id, event_type="withdrawal", amount="12500.50")
    assert exact.status_code == 201
    assert exact.json()["after"] == {"saved": "0.00"}
    assert goal(client, user_a, goal_id)["saved"] == "0.00"
    no_amount = event(client, user_a, goal_id, event_type="contribution")
    assert no_amount.json()["code"] == "goal.amount_required"


def test_reaching_the_target_records_achievement_by_the_system(client: TestClient, user_a: ApiUser):
    goal_id = create_goal(client, user_a, target_amount="1000.00")["id"]
    event(client, user_a, goal_id, event_type="contribution", amount="999.99")
    assert goal(client, user_a, goal_id)["status"] == "active"
    event(client, user_a, goal_id, event_type="contribution", amount="0.01")  # exactly 1000.00

    body = goal(client, user_a, goal_id)
    assert body["status"] == "achieved"
    last = body["events"][-1]
    assert (last["event_type"], last["actor"], last["after"]) == (
        "status_changed",
        "system",
        {"status": "achieved"},
    )


def test_every_change_is_recorded(client: TestClient, user_a: ApiUser):
    goal_id = create_goal(client, user_a, target_amount="5000.00")["id"]
    event(client, user_a, goal_id, event_type="contribution", amount="3000")
    event(client, user_a, goal_id, event_type="note", note="Waiting for the sale")
    url = f"/api/v1/goals/{goal_id}"
    client.patch(url, json={"target_date": "2027-01-31"}, headers=user_a.headers)
    client.patch(url, json={"name": "Phone 2", "priority": 1}, headers=user_a.headers)
    # Lowering the target below what is saved achieves the goal automatically.
    client.patch(url, json={"target_amount": "2500.00"}, headers=user_a.headers)
    client.patch(url, json={"status": "abandoned"}, headers=user_a.headers)

    events = goal(client, user_a, goal_id)["events"]
    assert [(e["event_type"], e["actor"]) for e in events] == [
        ("created", "user"),
        ("contribution", "user"),
        ("note", "user"),
        ("date_changed", "user"),
        ("details_changed", "user"),
        ("target_changed", "user"),
        ("status_changed", "system"),  # achieved: saved 3000 >= new target 2500
        ("status_changed", "user"),  # abandoned
    ]
    assert events[4]["before"] == {"name": "New phone", "priority": 3}
    assert events[5]["before"] == {"target_amount": "5000.00"}
    blocked = event(client, user_a, goal_id, event_type="contribution", amount="1")
    assert blocked.json()["code"] == "goal.abandoned"


def test_goal_history_is_append_only_in_the_database(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    goal_id = create_goal(client, user_a)["id"]
    event_id = db_session.scalars(select(GoalEvent.id).where(GoalEvent.goal_id == goal_id)).first()
    for statement in (
        "UPDATE goal_events SET note = 'x' WHERE id = :id",
        "DELETE FROM goal_events WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
            db_session.execute(text(statement), {"id": event_id})


# --- projections --------------------------------------------------------------------------------


def test_projection_with_a_given_monthly_saving(client: TestClient, user_a: ApiUser):
    goal_id = create_goal(client, user_a, target_date="2027-05-18")["id"]
    event(client, user_a, goal_id, event_type="contribution", amount="15000")
    body = client.get(
        f"/api/v1/goals/{goal_id}/projection?monthly_saving=5000", headers=user_a.headers
    ).json()
    # remaining 45000 - 15000 = 30000; 30000 / 5000 = 6 months -> 18 May 2027
    # target 18 May 2027 is 6 whole months away; required 30000 / 6 = 5000.00 -> on track
    assert {
        k: body[k]
        for k in (
            "status",
            "remaining",
            "months_needed",
            "projected_date",
            "months_until_target",
            "required_monthly",
            "on_track",
        )
    } == {
        "status": "ok",
        "remaining": "30000.00",
        "months_needed": 6,
        "projected_date": "2027-05-18",
        "months_until_target": 6,
        "required_monthly": "5000.00",
        "on_track": True,
    }
    assert body["monthly_saving_source"] == "given"
    assert body["assumptions"]
    bad = client.get(f"/api/v1/goals/{goal_id}/projection?monthly_saving=0", headers=user_a.headers)
    assert bad.json()["code"] == "goal.invalid_monthly_saving"


def test_projection_without_history_says_so(client: TestClient, user_a: ApiUser):
    goal_id = create_goal(client, user_a)["id"]
    body = client.get(f"/api/v1/goals/{goal_id}/projection", headers=user_a.headers).json()
    assert body["status"] == "insufficient_history"
    assert body["months_needed"] is None


@pytest.fixture
def history(db_session: Session, user_a: ApiUser):
    """Two complete months: Sep cash flow 50000 - 30000 = 20000; Oct 50000 - 40000 = 10000.
    November (current, not complete): one expense of 3500.
    Bank balance (no anchor): 50000 - 30000 + 50000 - 40000 - 3500 = 26500.00."""
    bank = add_account(db_session, user_a.id)
    add_tx(db_session, user_a.id, bank.id, date(2026, 9, 1), "50000.00", "credit")
    add_tx(db_session, user_a.id, bank.id, date(2026, 9, 2), "30000.00")
    add_tx(db_session, user_a.id, bank.id, date(2026, 10, 1), "50000.00", "credit")
    add_tx(db_session, user_a.id, bank.id, date(2026, 10, 2), "40000.00")
    add_tx(db_session, user_a.id, bank.id, date(2026, 11, 2), "3500.00")
    return bank


def test_projection_uses_the_median_of_complete_months(
    client: TestClient, user_a: ApiUser, history
):
    goal_id = create_goal(client, user_a)["id"]
    event(client, user_a, goal_id, event_type="contribution", amount="15000")
    body = client.get(f"/api/v1/goals/{goal_id}/projection", headers=user_a.headers).json()
    # median(20000, 10000) = 15000 per month; remaining 30000 / 15000 = 2 -> 18 Jan 2027
    assert (body["monthly_saving"], body["monthly_saving_source"]) == (
        "15000.00",
        "median_of_recent_months",
    )
    assert (body["months_needed"], body["projected_date"]) == (2, "2027-01-18")


ROW_COUNTED = (Transaction, TransactionEvent, Goal, GoalEvent, Budget, Job, AccessAudit)


def row_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in ROW_COUNTED
    }


def test_purchase_scenario_reports_impacts_and_writes_nothing(
    client: TestClient, user_a: ApiUser, history, db_session: Session
):
    goal_id = create_goal(client, user_a)["id"]
    event(client, user_a, goal_id, event_type="contribution", amount="15000")
    client.post(
        "/api/v1/budgets", json={"month": "2026-11", "amount": "5000.00"}, headers=user_a.headers
    )
    before = row_counts(db_session)

    response = client.post(
        "/api/v1/scenarios/purchase",
        json={"amount": "7000.00", "account_id": str(history.id)},
        headers=user_a.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert row_counts(db_session) == before  # nothing written
    assert body["written"] is False
    # balance 26500.00 - 7000.00 = 19500.00 (an estimate: no statement)
    assert (body["balance_before"]["balance"], body["balance_after"]) == ("26500.00", "19500.00")
    assert body["balance_before"]["status"] == "estimated"
    # November net spending 3500.00 -> 10500.00
    assert (body["month_net_spending_before"], body["month_net_spending_after"]) == (
        "3500.00",
        "10500.00",
    )
    # all-spending budget 5000: 3500 is ok (threshold 4000); 10500 is over
    (budget,) = body["budgets"]
    assert (budget["status_before"], budget["status_after"]) == ("ok", "over")
    # rate 15000; remaining 30000 -> 2 months; 30000 + 7000 = 37000 -> 3 months; delay 1
    (impact,) = body["goals"]
    assert (impact["remaining"], impact["delay_months"]) == ("30000.00", 1)


def test_purchase_scenario_touches_only_the_given_category_budget(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    categories = client.get("/api/v1/categories", headers=user_a.headers).json()["items"]
    food = next(c["id"] for c in categories if c["name"] == "Food & Dining")
    travel = next(c["id"] for c in categories if c["name"] == "Travel")
    for category in (food, travel):
        client.post(
            "/api/v1/budgets",
            json={"category_id": category, "month": "2026-11", "amount": "1000"},
            headers=user_a.headers,
        )
    body = client.post(
        "/api/v1/scenarios/purchase",
        json={"amount": "900.00", "category_id": travel},
        headers=user_a.headers,
    ).json()
    # 0 + 900 = 900 >= 80% of 1000 -> warning; the Food budget is not affected
    assert [(b["category_name"], b["status_after"]) for b in body["budgets"]] == [
        ("Travel", "warning")
    ]
    assert body["goals"] == []
    assert body["balance_before"] is None
