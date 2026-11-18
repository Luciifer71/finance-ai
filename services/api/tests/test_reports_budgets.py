"""M6: reports (6.3) and budgets (6.8). Every expected number is worked out by hand below.

Fixture (all 2028; bank account B, wallet W):
  Jan 25  expense  Shopping   2,000.00   (refunded partly in February)
  Feb 01  income   Salary    50,000.00
  Feb 03  expense  Food         450.00
  Feb 10  expense  Groceries  1,200.50
  Feb 14  expense  Shopping   3,000.00
  Feb 15  expense  Food      10,000.00   EXCLUDED
  Feb 20  transfer B -> W     5,000.00   (two rows, never spending)
  Feb 28  expense  Food         300.00   (Monday: ISO week 28 Feb - 5 Mar)
  Feb 29  expense  Groceries     99.50   (leap day)
  Feb 29  refund                800.00   linked to the Jan 25 Shopping purchase
  Mar 02  expense  Food         150.00
  Mar 03  income   Interest   1,000.00
"""

import uuid
from datetime import date
from decimal import Decimal

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.domain.budgets import budget_status, project_month_end
from app.domain.periods import buckets, period_bounds
from app.domain.reports import LedgerEntry, period_totals
from app.models import Category, Transaction
from app.repositories import reports as report_repo
from tests.conftest import ApiUser
from tests.factories import add_account, add_tx

D = Decimal


def cat(session: Session, user_id: uuid.UUID, name: str) -> uuid.UUID:
    return session.scalars(
        select(Category.id).where(Category.user_id == user_id, Category.name == name)
    ).one()


@pytest.fixture
def ledger(db_session: Session, user_a: ApiUser) -> dict[str, uuid.UUID]:
    uid = user_a.id
    bank = add_account(db_session, uid, "Bank")
    wallet = add_account(db_session, uid, "Wallet", "wallet")
    food, groceries = cat(db_session, uid, "Food & Dining"), cat(db_session, uid, "Groceries")
    shopping, salary = cat(db_session, uid, "Shopping"), cat(db_session, uid, "Salary")
    interest = cat(db_session, uid, "Interest")

    def expense(day: date, amount: str, category: uuid.UUID, **kw: object) -> Transaction:
        return add_tx(db_session, uid, bank.id, day, amount, category_id=category,
                      category_source="user", **kw)  # fmt: skip

    jan_purchase = expense(date(2028, 1, 25), "2000.00", shopping)
    add_tx(db_session, uid, bank.id, date(2028, 2, 1), "50000.00", "credit", category_id=salary)
    expense(date(2028, 2, 3), "450.00", food)
    expense(date(2028, 2, 10), "1200.50", groceries)
    expense(date(2028, 2, 14), "3000.00", shopping)
    expense(date(2028, 2, 15), "10000.00", food, is_excluded=True)
    group = uuid.uuid4()
    add_tx(db_session, uid, bank.id, date(2028, 2, 20), "5000.00", "debit", "transfer",
           transfer_group_id=group)  # fmt: skip
    add_tx(db_session, uid, wallet.id, date(2028, 2, 20), "5000.00", "credit", "transfer",
           transfer_group_id=group)  # fmt: skip
    expense(date(2028, 2, 28), "300.00", food)
    expense(date(2028, 2, 29), "99.50", groceries)
    add_tx(db_session, uid, bank.id, date(2028, 2, 29), "800.00", "credit", "refund",
           refund_of_id=jan_purchase.id)  # fmt: skip
    expense(date(2028, 3, 2), "150.00", food)
    add_tx(db_session, uid, bank.id, date(2028, 3, 3), "1000.00", "credit", category_id=interest)
    return {"food": food, "groceries": groceries, "shopping": shopping}


def summary(client: TestClient, user: ApiUser, period: str, on: str) -> dict:
    response = client.get(
        f"/api/v1/reports/summary?period={period}&date={on}", headers=user.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- totals for day, ISO week, month, year --------------------------------------------------


def test_month_totals(client: TestClient, user_a: ApiUser, ledger):
    body = summary(client, user_a, "month", "2028-02-17")
    assert (body["start"], body["end"]) == ("2028-02-01", "2028-02-29")
    # gross 450 + 1200.50 + 3000 + 300 + 99.50 = 5050.00 (excluded 10,000 and transfers out)
    # refunds 800.00; net 4250.00; income 50,000.00; cash flow 50000 + 800 - 5050 = 45750.00
    assert body["totals"] == {
        "gross_spending": "5050.00",
        "refunds": "800.00",
        "net_spending": "4250.00",
        "income": "50000.00",
        "net_cash_flow": "45750.00",
    }


def test_leap_day_totals(client: TestClient, user_a: ApiUser, ledger):
    body = summary(client, user_a, "day", "2028-02-29")
    # expense 99.50, refund 800.00 -> net -700.50; cash flow 0 + 800 - 99.50 = 700.50
    assert body["totals"] == {
        "gross_spending": "99.50",
        "refunds": "800.00",
        "net_spending": "-700.50",
        "income": "0.00",
        "net_cash_flow": "700.50",
    }


def test_iso_week_spanning_two_months(client: TestClient, user_a: ApiUser, ledger):
    body = summary(client, user_a, "week", "2028-03-01")
    assert (body["start"], body["end"]) == ("2028-02-28", "2028-03-05")  # Monday to Sunday
    # expenses 300 + 99.50 + 150 = 549.50; refund 800; net -250.50;
    # income 1000; cash flow 1000 + 800 - 549.50 = 1250.50
    assert body["totals"] == {
        "gross_spending": "549.50",
        "refunds": "800.00",
        "net_spending": "-250.50",
        "income": "1000.00",
        "net_cash_flow": "1250.50",
    }


def test_year_totals(client: TestClient, user_a: ApiUser, ledger):
    body = summary(client, user_a, "year", "2028-06-01")
    # expenses 2000 + 5050 + 150 = 7200.00; refunds 800; net 6400.00;
    # income 51,000.00; cash flow 51000 + 800 - 7200 = 44600.00
    assert body["totals"] == {
        "gross_spending": "7200.00",
        "refunds": "800.00",
        "net_spending": "6400.00",
        "income": "51000.00",
        "net_cash_flow": "44600.00",
    }


def test_summary_defaults_to_the_current_month(client: TestClient, user_a: ApiUser, ledger):
    body = client.get("/api/v1/reports/summary", headers=user_a.headers).json()
    assert (body["period"], body["start"], body["end"]) == ("month", "2026-11-01", "2026-11-30")
    assert body["totals"]["net_spending"] == "0.00"


def test_monthly_timeseries_includes_empty_periods(client: TestClient, user_a: ApiUser, ledger):
    body = client.get(
        "/api/v1/reports/timeseries?granularity=month&from=2027-12-01&to=2028-03-31",
        headers=user_a.headers,
    ).json()
    assert [(b["start"], b["totals"]["net_spending"]) for b in body["buckets"]] == [
        ("2027-12-01", "0.00"),
        ("2028-01-01", "2000.00"),
        ("2028-02-01", "4250.00"),
        ("2028-03-01", "150.00"),
    ]
    assert body["from"] == "2027-12-01"


def test_weekly_timeseries_clips_to_the_range(client: TestClient, user_a: ApiUser, ledger):
    body = client.get(
        "/api/v1/reports/timeseries?granularity=week&from=2028-02-26&to=2028-03-02",
        headers=user_a.headers,
    ).json()
    # Week of 21-27 Feb clipped to 26-27 Feb (no rows); week 28 Feb - 5 Mar clipped to 2 Mar:
    # 300 + 99.50 + 150 = 549.50 gross
    assert [(b["start"], b["end"], b["totals"]["gross_spending"]) for b in body["buckets"]] == [
        ("2028-02-26", "2028-02-27", "0.00"),
        ("2028-02-28", "2028-03-02", "549.50"),
    ]


def test_categories_with_refund_reducing_the_original_category(
    client: TestClient, user_a: ApiUser, ledger
):
    body = client.get(
        "/api/v1/reports/categories?from=2028-02-01&to=2028-02-29", headers=user_a.headers
    ).json()
    # Shopping 3000 - 800 (refund of the January Shopping purchase) = 2200.00
    # Groceries 1200.50 + 99.50 = 1300.00; Food 450 + 300 = 750.00 (excluded 10,000 left out)
    # Shares of 4250.00: 51.8%, 30.6%, 17.6%
    assert [
        (i["name"], i["gross_spending"], i["refunds"], i["net_spending"], i["share_percent"])
        for i in body["items"]
    ] == [
        ("Shopping", "3000.00", "800.00", "2200.00", "51.8"),
        ("Groceries", "1300.00", "0.00", "1300.00", "30.6"),
        ("Food & Dining", "750.00", "0.00", "750.00", "17.6"),
    ]
    assert body["total_net_spending"] == "4250.00"


def test_sql_totals_match_the_domain_definition(db_session: Session, user_a: ApiUser, ledger):
    rows = db_session.scalars(select(Transaction).where(Transaction.user_id == user_a.id)).all()
    entries = [
        LedgerEntry(r.amount, r.transaction_type, r.posted_on, is_excluded=r.is_excluded)
        for r in rows
    ]
    for granularity in ("day", "week", "month", "year"):
        for start, _end in buckets(granularity, date(2028, 1, 1), date(2028, 3, 31)):
            bounds = period_bounds(granularity, start)
            expected = period_totals(entries, *bounds)
            assert report_repo.period_totals(db_session, user_a.id, *bounds) == expected


def test_report_validation(client: TestClient, user_a: ApiUser):
    bad_range = client.get(
        "/api/v1/reports/categories?from=2028-03-01&to=2028-02-01", headers=user_a.headers
    )
    assert bad_range.json()["code"] == "report.invalid_range"
    too_long = client.get(
        "/api/v1/reports/timeseries?granularity=day&from=2027-01-01&to=2028-12-31",
        headers=user_a.headers,
    )
    assert too_long.json()["code"] == "report.too_many_buckets"
    assert client.get(
        "/api/v1/reports/summary?period=decade", headers=user_a.headers
    ).status_code == (422)


def test_reports_are_per_user(client: TestClient, user_a: ApiUser, user_b: ApiUser, ledger):
    assert summary(client, user_b, "year", "2028-01-01")["totals"]["gross_spending"] == "0.00"


# --- budgets ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spent", "status"),
    [("799.99", "ok"), ("800.00", "warning"), ("999.99", "warning"), ("1000.00", "over"),
     ("1500.00", "over")],
)  # fmt: skip
def test_budget_status_boundaries(spent: str, status: str):
    # amount 1000.00, warn at 80% -> threshold 800.00
    assert budget_status(D("1000.00"), 80, D(spent)) == status


def test_projection_rules():
    feb = date(2028, 2, 1)
    # Day 6: fewer than 7 days elapsed
    early = project_month_end(feb, date(2028, 2, 6), D("600.00"), D("3000.00"))
    assert (early.projected, early.reason) == (None, "too_early_in_month")
    # Day 7: 700 / 7 * 29 = 2900.00 < 3000 -> may not exceed
    day7 = project_month_end(feb, date(2028, 2, 7), D("700.00"), D("3000.00"))
    assert (day7.projected, day7.may_exceed, day7.days_in_month) == (D("2900"), False, 29)
    # Day 10: 1300 / 10 * 29 = 3770.00 >= 3000 -> may exceed
    day10 = project_month_end(feb, date(2028, 2, 10), D("1300.00"), D("3000.00"))
    assert (day10.projected, day10.may_exceed) == (D("3770"), True)
    other = project_month_end(feb, date(2028, 3, 10), D("1.00"), D("3000.00"))
    assert other.reason == "not_current_month"


def create_budget(client: TestClient, user: ApiUser, **body: object):
    return client.post("/api/v1/budgets", json=body, headers=user.headers)


def test_budget_status_for_a_past_month(client: TestClient, user_a: ApiUser, ledger):
    shopping = create_budget(client, user_a, category_id=str(ledger["shopping"]), month="2028-02",
                             amount="2,200.00")  # fmt: skip
    food = create_budget(client, user_a, category_id=str(ledger["food"]), month="2028-02",
                         amount="1000.00", warn_at_percent=75)  # fmt: skip
    total = create_budget(client, user_a, month="2028-02", amount="10000.00")
    assert {r.status_code for r in (shopping, food, total)} == {201}

    body = client.get("/api/v1/budgets/status?month=2028-02", headers=user_a.headers).json()
    by_name = {i["category_name"]: i for i in body["items"]}

    # Shopping: net 2200.00 == amount 2200.00 -> over (exactly at the amount)
    assert (by_name["Shopping"]["spent"], by_name["Shopping"]["status"]) == ("2200.00", "over")
    assert by_name["Shopping"]["percent_used"] == "100.0"
    # Food: 750.00 vs threshold 1000 x 75% = 750.00 -> warning (exactly at the threshold)
    assert (by_name["Food & Dining"]["warn_threshold"], by_name["Food & Dining"]["status"]) == (
        "750.00",
        "warning",
    )
    # All spending: net 4250.00 of 10000.00 -> ok, 42.5%, remaining 5750.00
    assert (by_name[None]["spent"], by_name[None]["status"], by_name[None]["remaining"]) == (
        "4250.00",
        "ok",
        "5750.00",
    )
    assert by_name[None]["percent_used"] == "42.5"
    assert by_name[None]["projection"]["reason"] == "not_current_month"


def _user_at(user: ApiUser, make_token, when: FixedClock) -> ApiUser:
    """The same user with a token valid at ``when`` (the old one would look expired)."""
    claims = jwt.decode(user.token, options={"verify_signature": False})
    token = make_token(claims["sub"], claims["email"], now=when.now())
    return ApiUser(id=user.id, email=user.email, token=token)


def test_budget_projection_in_the_current_month(
    app: FastAPI, client: TestClient, user_a: ApiUser, ledger, make_token
):
    feb10 = FixedClock.at_date(date(2028, 2, 10))
    app.state.clock = feb10
    user_a = _user_at(user_a, make_token, feb10)
    create_budget(client, user_a, category_id=str(ledger["groceries"]), month="2028-02",
                  amount="3000.00")  # fmt: skip
    (item,) = client.get("/api/v1/budgets/status", headers=user_a.headers).json()["items"]
    # Section 6.8: spent = net spending of the whole month: Groceries 1200.50 + 99.50 = 1300.00
    # projected 1300.00 / 10 x 29 = 3770.00 >= 3000 -> may exceed
    assert item["spent"] == "1300.00"
    assert item["projection"] == {
        "projected_spending": "3770.00",
        "may_exceed": True,
        "reason": None,
        "days_elapsed": 10,
        "days_in_month": 29,
        "formula": "spent / days_elapsed * days_in_month",
    }

    feb6 = FixedClock.at_date(date(2028, 2, 6))
    app.state.clock = feb6
    user_a = _user_at(user_a, make_token, feb6)
    (early,) = client.get("/api/v1/budgets/status", headers=user_a.headers).json()["items"]
    assert (early["projection"]["projected_spending"], early["projection"]["reason"]) == (
        None,
        "too_early_in_month",
    )


def test_negative_net_spending_counts_as_zero_spent(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    bank = add_account(db_session, user_a.id)
    shopping = cat(db_session, user_a.id, "Shopping")
    original = add_tx(db_session, user_a.id, bank.id, date(2028, 1, 5), "500.00",
                      category_id=shopping)  # fmt: skip
    add_tx(db_session, user_a.id, bank.id, date(2028, 2, 2), "500.00", "credit", "refund",
           refund_of_id=original.id)  # fmt: skip
    create_budget(client, user_a, category_id=str(shopping), month="2028-02", amount="100.00")
    (item,) = client.get("/api/v1/budgets/status?month=2028-02", headers=user_a.headers).json()[
        "items"
    ]
    assert (item["net_spending"], item["spent"], item["status"]) == ("-500.00", "0.00", "ok")


def test_budget_crud_and_rules(client: TestClient, user_a: ApiUser, db_session: Session):
    food = cat(db_session, user_a.id, "Food & Dining")
    salary = cat(db_session, user_a.id, "Salary")
    created = create_budget(client, user_a, category_id=str(food), month="2026-11", amount="5000")
    assert created.status_code == 201
    budget = created.json()
    assert (budget["month"], budget["amount"], budget["warn_at_percent"]) == (
        "2026-11",
        "5000.00",
        80,
    )

    duplicate = create_budget(client, user_a, category_id=str(food), month="2026-11", amount="1")
    assert duplicate.json()["code"] == "budget.already_exists"
    create_budget(client, user_a, month="2026-11", amount="20000")
    second_total = create_budget(client, user_a, month="2026-11", amount="1")
    assert second_total.json()["code"] == "budget.already_exists"  # NULLS NOT DISTINCT
    assert create_budget(client, user_a, category_id=str(salary), month="2026-11",
                         amount="1").json()["code"] == "budget.category_not_expense"  # fmt: skip
    for bad in ({"month": "2026-13", "amount": "1"}, {"month": "2026-11", "amount": "0"},
                {"month": "2026-11", "amount": "1", "warn_at_percent": 0}):  # fmt: skip
        assert create_budget(client, user_a, **bad).status_code == 422

    url = f"/api/v1/budgets/{budget['id']}"
    updated = client.patch(url, json={"amount": "6000.00", "warn_at_percent": 90},
                           headers=user_a.headers).json()  # fmt: skip
    assert (updated["amount"], updated["warn_at_percent"]) == ("6000.00", 90)
    listed = client.get("/api/v1/budgets?month=2026-11", headers=user_a.headers).json()["items"]
    assert len(listed) == 2
    assert client.delete(url, headers=user_a.headers).status_code == 204
    assert client.get(url, headers=user_a.headers).status_code == 404
