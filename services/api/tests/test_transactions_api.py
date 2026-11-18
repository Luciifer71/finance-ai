"""M2: transaction list/search/detail, cursor pagination, manual transactions."""

import hashlib
import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.pagination import encode_cursor
from tests.conftest import ApiUser
from tests.factories import add_account, add_tx


def category_id(client: TestClient, user: ApiUser, name: str) -> str:
    items = client.get("/api/v1/categories", headers=user.headers).json()["items"]
    return next(c["id"] for c in items if c["name"] == name)


def manual(client: TestClient, user: ApiUser, **body: object):
    return client.post("/api/v1/transactions", json=body, headers=user.headers)


# --- manual transactions ---------------------------------------------------------------------


def test_manual_expense_defaults_from_direction(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id, "Cash", "cash")
    response = manual(
        client,
        user_a,
        account_id=str(account.id),
        posted_on="2026-11-17",
        amount="₹ 1,250.5",
        direction="debit",
        description="Vegetables at the market",
        category_id=category_id(client, user_a, "Groceries"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["transaction_type"] == "expense"
    assert (body["amount"], body["signed_amount"]) == ("1250.50", "-1250.50")
    assert body["source"] == "manual"
    assert "fingerprint" not in body  # internal detail, not part of the contract

    from app.models import Transaction

    stored = db_session.get(Transaction, body["id"])
    assert stored is not None
    assert stored.fingerprint == hashlib.sha256(f"manual{body['id']}".encode()).hexdigest()


def test_manual_credit_defaults_to_income(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    response = manual(
        client, user_a, account_id=str(account.id), posted_on="2026-11-01", amount="50000",
        direction="credit",
    )  # fmt: skip
    assert response.json()["transaction_type"] == "income"
    assert response.json()["signed_amount"] == "50000.00"


def test_manual_transaction_rules(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    base = {"account_id": str(account.id), "posted_on": "2026-11-01", "amount": "10.00"}
    salary = category_id(client, user_a, "Salary")
    cases = [
        ({"direction": "credit", "transaction_type": "expense"}, 422),  # expense must be debit
        ({"direction": "debit", "transaction_type": "income"}, 422),
        ({"direction": "debit", "transaction_type": "transfer"}, 422),  # use pairing instead
        ({"direction": "debit", "category_id": salary}, 422),  # income category on an expense
        ({"direction": "debit", "amount": "0.00"}, 422),
        ({"direction": "debit", "amount": "-5.00"}, 422),
        ({"direction": "debit", "occurred_at": "2026-11-01T10:00:00"}, 422),  # naive time
        ({"direction": "sideways"}, 422),
    ]
    for override, expected in cases:
        response = manual(client, user_a, **{**base, **override})
        assert response.status_code == expected, (override, response.text)


def test_refund_can_be_recorded_manually_with_expense_category(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    response = manual(
        client, user_a, account_id=str(account.id), posted_on="2026-11-02", amount="499.00",
        direction="credit", transaction_type="refund",
        category_id=category_id(client, user_a, "Shopping"),
    )  # fmt: skip
    assert response.status_code == 201
    assert response.json()["transaction_type"] == "refund"


def test_archived_account_or_category_cannot_be_used(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    fuel = category_id(client, user_a, "Fuel")
    client.patch(f"/api/v1/categories/{fuel}", json={"is_archived": True}, headers=user_a.headers)
    response = manual(
        client, user_a, account_id=str(account.id), posted_on="2026-11-02", amount="1.00",
        direction="debit", category_id=fuel,
    )  # fmt: skip
    assert response.status_code == 409
    assert response.json()["code"] == "category.archived"

    client.patch(
        f"/api/v1/accounts/{account.id}", json={"is_archived": True}, headers=user_a.headers
    )
    response = manual(
        client, user_a, account_id=str(account.id), posted_on="2026-11-02", amount="1.00",
        direction="debit",
    )  # fmt: skip
    assert response.json()["code"] == "account.archived"


def test_cannot_use_another_users_account_or_category(
    client: TestClient, user_a: ApiUser, user_b: ApiUser, db_session: Session
):
    account_a = add_account(db_session, user_a.id)
    account_b = add_account(db_session, user_b.id)
    response = manual(
        client, user_b, account_id=str(account_a.id), posted_on="2026-11-02", amount="1.00",
        direction="debit",
    )  # fmt: skip
    assert response.status_code == 404
    response = manual(
        client, user_b, account_id=str(account_b.id), posted_on="2026-11-02", amount="1.00",
        direction="debit", category_id=category_id(client, user_a, "Fuel"),
    )  # fmt: skip
    assert response.status_code == 404


# --- list, search, detail -------------------------------------------------------------------


def _ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_filters_and_search(client: TestClient, user_a: ApiUser, db_session: Session):
    bank = add_account(db_session, user_a.id)
    cash = add_account(db_session, user_a.id, "Cash", "cash")
    food = category_id(client, user_a, "Food & Dining")
    swiggy = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 3), "350.00",
                    description="UPI/SWIGGY/ORDER", category_id=food)  # fmt: skip
    salary = add_tx(db_session, user_a.id, bank.id, date(2026, 11, 1), "60000.00", "credit",
                    description="SALARY NOV")  # fmt: skip
    chai = add_tx(
        db_session, user_a.id, cash.id, date(2026, 11, 5), "20.00", description="chai 100%"
    )
    headers = user_a.headers

    def get(query: str) -> list[str]:
        return _ids(client.get(f"/api/v1/transactions?{query}", headers=headers))

    assert get("") == [str(chai.id), str(swiggy.id), str(salary.id)]  # newest first
    assert get(f"account_id={cash.id}") == [str(chai.id)]
    assert get(f"category_id={food}") == [str(swiggy.id)]
    assert get("type=income") == [str(salary.id)]
    assert get("from=2026-11-02&to=2026-11-04") == [str(swiggy.id)]
    assert get("q=swiggy") == [str(swiggy.id)]  # case-insensitive
    assert get("q=100%25") == [str(chai.id)]  # a literal % is not a wildcard
    assert get("q=%25") == [str(chai.id)]
    assert get("min_amount=300&max_amount=1,000") == [str(swiggy.id)]
    assert client.get("/api/v1/transactions?min_amount=1e3", headers=headers).status_code == 422
    assert client.get("/api/v1/transactions?limit=0", headers=headers).status_code == 422
    assert client.get("/api/v1/transactions?limit=201", headers=headers).status_code == 422


def test_pagination_returns_every_row_exactly_once_with_ties(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    # 3 rows on 5 Nov, 3 on 4 Nov, 1 on 3 Nov: ties on posted_on across page boundaries.
    created = [
        add_tx(db_session, user_a.id, account.id, date(2026, 11, d), f"{i + 1}.00")
        for i, d in enumerate([5, 5, 5, 4, 4, 4, 3])
    ]
    expected = [str(t.id) for t in sorted(created, key=lambda t: (t.posted_on, t.id), reverse=True)]

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        query = "limit=3" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(f"/api/v1/transactions?{query}", headers=user_a.headers).json()
        seen += [item["id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == expected
    assert pages == 3  # 3 + 3 + 1


def test_exact_multiple_of_page_size_has_no_empty_last_page(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    account = add_account(db_session, user_a.id)
    for d in (1, 2):
        add_tx(db_session, user_a.id, account.id, date(2026, 11, d), "1.00")
    body = client.get("/api/v1/transactions?limit=2", headers=user_a.headers).json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


def test_invalid_cursor_is_rejected(client: TestClient, user_a: ApiUser):
    truncated = encode_cursor(date(2026, 1, 1), uuid.uuid4())[:-3]
    for cursor in ("not-base64!!", "e30", truncated):
        response = client.get(f"/api/v1/transactions?cursor={cursor}", headers=user_a.headers)
        assert response.status_code == 422, cursor
        assert response.json()["code"] == "pagination.invalid_cursor"


def test_detail_and_404(client: TestClient, user_a: ApiUser, db_session: Session):
    account = add_account(db_session, user_a.id)
    tx = add_tx(db_session, user_a.id, account.id, date(2026, 11, 3), "350.00")
    response = client.get(f"/api/v1/transactions/{tx.id}", headers=user_a.headers)
    assert response.status_code == 200
    assert response.json()["posted_on"] == "2026-11-03"
    missing = client.get(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000000", headers=user_a.headers
    )
    assert missing.json()["code"] == "transaction.not_found"
