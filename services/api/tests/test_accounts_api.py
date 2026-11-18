"""M2: accounts, opening balances, balances with status, reconciliation (via the API)."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import ApiUser
from tests.factories import add_statement_snapshot, add_tx


def create_account(client: TestClient, user: ApiUser, **overrides: object) -> dict:
    body = {"name": "HDFC Savings", "account_type": "bank", "institution": "HDFC Bank"}
    body.update(overrides)
    response = client.post("/api/v1/accounts", json=body, headers=user.headers)
    assert response.status_code == 201, response.text
    return response.json()


def balance(client: TestClient, user: ApiUser, account_id: str, as_of: str | None = None) -> dict:
    url = f"/api/v1/accounts/{account_id}/balance" + (f"?as_of={as_of}" if as_of else "")
    response = client.get(url, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_new_account_has_zero_balance_and_no_anchor(client: TestClient, user_a: ApiUser):
    account = create_account(client, user_a, last4="1234")

    assert account["currency"] == "INR"
    assert account["last4"] == "1234"
    assert account["is_archived"] is False
    assert account["balance"] == {
        "as_of": "2026-11-18",  # the frozen "today" in India
        "balance": "0.00",
        "status": "estimated",
        "reason": "no_anchor",
        "verified_as_of": None,
        "anchor": None,
        "transactions_since_anchor": 0,
    }


def test_account_validation(client: TestClient, user_a: ApiUser):
    for bad in (
        {"name": "", "account_type": "bank"},
        {"name": "X", "account_type": "crypto"},
        {"name": "X", "account_type": "bank", "last4": "12a4"},
        {"name": "X", "account_type": "bank", "balance": "5.00"},  # unknown field
    ):
        response = client.post("/api/v1/accounts", json=bad, headers=user_a.headers)
        assert response.status_code == 422, bad


def test_rename_and_archive_instead_of_delete(client: TestClient, user_a: ApiUser):
    account = create_account(client, user_a)
    url = f"/api/v1/accounts/{account['id']}"

    renamed = client.patch(url, json={"name": "  Salary account "}, headers=user_a.headers)
    assert renamed.json()["name"] == "Salary account"
    archived = client.patch(url, json={"is_archived": True}, headers=user_a.headers)
    assert archived.json()["is_archived"] is True

    listed = client.get("/api/v1/accounts", headers=user_a.headers).json()["items"]
    assert account["id"] not in [a["id"] for a in listed]
    with_archived = client.get(
        "/api/v1/accounts?include_archived=true", headers=user_a.headers
    ).json()["items"]
    assert account["id"] in [a["id"] for a in with_archived]
    assert client.delete(url, headers=user_a.headers).status_code == 405


def test_name_cannot_be_cleared(client: TestClient, user_a: ApiUser):
    account = create_account(client, user_a)
    response = client.patch(
        f"/api/v1/accounts/{account['id']}", json={"name": None}, headers=user_a.headers
    )
    assert response.json()["name"] == "HDFC Savings"


def test_opening_balance_only_is_an_estimate(client: TestClient, user_a: ApiUser):
    account = create_account(client, user_a)
    response = client.post(
        f"/api/v1/accounts/{account['id']}/opening-balance",
        json={"as_of": "2026-11-01", "balance": "1,25,000.50"},
        headers=user_a.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == "125000.50"
    assert (body["status"], body["reason"]) == ("estimated", "no_statement")
    assert body["anchor"] == {
        "as_of": "2026-11-01",
        "balance": "125000.50",
        "source": "user_entered",
    }


def test_opening_balance_for_same_date_replaces_the_previous_one(
    client: TestClient, user_a: ApiUser
):
    account = create_account(client, user_a)
    url = f"/api/v1/accounts/{account['id']}/opening-balance"
    client.post(url, json={"as_of": "2026-11-01", "balance": "100.00"}, headers=user_a.headers)
    client.post(url, json={"as_of": "2026-11-01", "balance": "250.00"}, headers=user_a.headers)
    assert balance(client, user_a, account["id"])["balance"] == "250.00"


def test_money_must_be_a_string(client: TestClient, user_a: ApiUser):
    account = create_account(client, user_a)
    url = f"/api/v1/accounts/{account['id']}/opening-balance"
    for bad in (100.5, 100, "10.001", "1e3", ""):
        response = client.post(
            url, json={"as_of": "2026-11-01", "balance": bad}, headers=user_a.headers
        )
        assert response.status_code == 422, bad
        assert response.json()["errors"][0]["field"] == "balance"


def test_opening_balance_plus_transactions(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = create_account(client, user_a)
    account_id = account["id"]
    client.post(
        f"/api/v1/accounts/{account_id}/opening-balance",
        json={"as_of": "2026-11-01", "balance": "10000.00"},
        headers=user_a.headers,
    )
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 3), "1250.75")  # debit
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 5), "50000.00", "credit")
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 20), "99.00")  # after "today"

    # 10000.00 - 1250.75 + 50000.00 = 58749.25 (the 20 Nov row is in the future)
    body = balance(client, user_a, account_id)
    assert body["balance"] == "58749.25"
    assert body["transactions_since_anchor"] == 2
    # As of 25 Nov: 58749.25 - 99.00 = 58650.25
    assert balance(client, user_a, account_id, "2026-11-25")["balance"] == "58650.25"


def test_statement_snapshot_with_no_later_rows_is_verified(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account_id = create_account(client, user_a)["id"]
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 10), "500.00")
    add_statement_snapshot(db_session, user_a.id, account_id, date(2026, 11, 15), "7342.18")

    body = balance(client, user_a, account_id)
    assert body["balance"] == "7342.18"
    assert (body["status"], body["reason"], body["verified_as_of"]) == (
        "verified",
        None,
        "2026-11-15",
    )


def test_statement_then_later_rows_is_estimated(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account_id = create_account(client, user_a)["id"]
    add_statement_snapshot(db_session, user_a.id, account_id, date(2026, 11, 15), "7342.18")
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 16), "342.18")

    # 7342.18 - 342.18 = 7000.00
    body = balance(client, user_a, account_id)
    assert body["balance"] == "7000.00"
    assert (body["status"], body["reason"]) == ("estimated", "transactions_after_statement")


def test_negative_credit_card_balance(client: TestClient, user_a: ApiUser, db_session: Session):
    card_id = create_account(client, user_a, name="Card", account_type="credit")["id"]
    add_statement_snapshot(db_session, user_a.id, card_id, date(2026, 11, 1), "-15000.00")
    add_tx(db_session, user_a.id, card_id, date(2026, 11, 2), "3500.00")  # purchase
    add_tx(db_session, user_a.id, card_id, date(2026, 11, 9), "10000.00", "credit")  # payment

    # -15000.00 - 3500.00 + 10000.00 = -8500.00
    assert balance(client, user_a, card_id)["balance"] == "-8500.00"


def test_reconciliation_reports_matches_and_differences(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account_id = create_account(client, user_a)["id"]
    url = f"/api/v1/accounts/{account_id}/reconciliation"
    assert client.get(url, headers=user_a.headers).json()["status"] == "not_enough_statements"

    add_statement_snapshot(db_session, user_a.id, account_id, date(2026, 10, 31), "2000.00")
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 4), "450.00")
    add_tx(db_session, user_a.id, account_id, date(2026, 11, 7), "1000.00", "credit")
    # Oct 31 -> Nov 7: 2000.00 - 450.00 + 1000.00 = 2550.00 (statement agrees)
    add_statement_snapshot(db_session, user_a.id, account_id, date(2026, 11, 7), "2550.00")
    ok = client.get(url, headers=user_a.headers).json()
    assert ok["status"] == "ok"
    assert ok["pairs"][0]["difference"] == "0.00"
    assert balance(client, user_a, account_id)["status"] == "verified"

    add_tx(db_session, user_a.id, account_id, date(2026, 11, 12), "100.00")
    # Nov 7 -> Nov 14: 2550.00 - 100.00 = 2450.00 expected, statement says 2400.00
    add_statement_snapshot(db_session, user_a.id, account_id, date(2026, 11, 14), "2400.00")
    bad = client.get(url, headers=user_a.headers).json()
    assert bad["status"] == "mismatch"
    assert bad["pairs"][1] == {
        "start_as_of": "2026-11-07",
        "start_balance": "2550.00",
        "end_as_of": "2026-11-14",
        "end_balance": "2400.00",
        "movement": "-100.00",
        "expected_end_balance": "2450.00",
        "difference": "-50.00",
        "reconciles": False,
    }
    body = balance(client, user_a, account_id)
    assert (body["balance"], body["reason"]) == ("2400.00", "reconciliation_mismatch")


def test_unknown_account_is_404(client: TestClient, user_a: ApiUser):
    response = client.get(
        "/api/v1/accounts/00000000-0000-0000-0000-000000000000", headers=user_a.headers
    )
    assert response.status_code == 404
    assert response.json()["code"] == "account.not_found"
