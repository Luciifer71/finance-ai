"""Registers every user-scoped resource with the isolation harness (see isolation.py).

Each milestone adds its routes here. A route that reads or changes one user's
data by id must appear in some entry below.
"""

from fastapi.testclient import TestClient

from tests.conftest import ApiUser
from tests.isolation import IsolatedResource, register


def _create_account(client: TestClient, user: ApiUser) -> str:
    response = client.post(
        "/api/v1/accounts", json={"name": "Private", "account_type": "bank"}, headers=user.headers
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _create_category(client: TestClient, user: ApiUser) -> str:
    response = client.post(
        "/api/v1/categories",
        json={"name": "Private hobby", "kind": "expense"},
        headers=user.headers,
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _create_transaction(client: TestClient, user: ApiUser) -> str:
    account_id = _create_account(client, user)
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "posted_on": "2026-11-10",
            "amount": "123.45",
            "direction": "debit",
            "description": "private purchase",
        },
        headers=user.headers,
    )
    assert response.status_code == 201
    return str(response.json()["id"])


register(
    IsolatedResource(
        name="accounts",
        create=_create_account,
        detail="/api/v1/accounts/{id}",
        updates=[
            ("PATCH", "/api/v1/accounts/{id}", {"name": "stolen", "is_archived": True}),
            (
                "POST",
                "/api/v1/accounts/{id}/opening-balance",
                {"as_of": "2026-11-01", "balance": "1.00"},
            ),
        ],
        lists=["/api/v1/accounts?include_archived=true"],
    )
)
register(
    IsolatedResource(
        name="account_balance_and_reconciliation",
        create=_create_account,
        detail="/api/v1/accounts/{id}/balance",
        updates=[("GET", "/api/v1/accounts/{id}/reconciliation", {})],
    )
)
register(
    IsolatedResource(
        name="categories",
        create=_create_category,
        updates=[("PATCH", "/api/v1/categories/{id}", {"name": "stolen", "is_archived": True})],
        lists=["/api/v1/categories?include_archived=true"],
    )
)
register(
    IsolatedResource(
        name="transactions",
        create=_create_transaction,
        detail="/api/v1/transactions/{id}",
        lists=["/api/v1/transactions", "/api/v1/transactions?include_excluded=true"],
    )
)


def _create_import(client: TestClient, user: ApiUser) -> str:
    account_id = _create_account(client, user)
    response = client.post(
        "/api/v1/imports",
        files={
            "file": ("s.csv", b"date,description,amount\n2026-11-05,private,-9.99\n", "text/csv")
        },
        data={"account_id": account_id, "profile_id": "simple_v1"},
        headers=user.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


register(
    IsolatedResource(
        name="imports",
        create=_create_import,
        detail="/api/v1/imports/{id}",
        updates=[
            ("POST", "/api/v1/imports/{id}/commit", {}),
            ("POST", "/api/v1/imports/{id}/cancel", {}),
        ],
        lists=["/api/v1/imports"],
    )
)
