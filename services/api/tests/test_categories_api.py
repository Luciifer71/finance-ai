"""M2: categories (defaults, create, rename, archive, Uncategorized protection)."""

from fastapi.testclient import TestClient

from tests.conftest import ApiUser


def categories(client: TestClient, user: ApiUser, include_archived: bool = False) -> list[dict]:
    url = "/api/v1/categories" + ("?include_archived=true" if include_archived else "")
    return client.get(url, headers=user.headers).json()["items"]


def by_name(client: TestClient, user: ApiUser, name: str) -> dict:
    return next(c for c in categories(client, user, True) if c["name"] == name)


def test_new_user_has_default_categories(client: TestClient, user_a: ApiUser):
    items = categories(client, user_a)
    assert len(items) == 21
    assert {"Uncategorized", "Food & Dining", "Salary"} <= {c["name"] for c in items}


def test_create_category(client: TestClient, user_a: ApiUser):
    response = client.post(
        "/api/v1/categories", json={"name": " Pets ", "kind": "expense"}, headers=user_a.headers
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Pets"


def test_duplicate_name_ignoring_case_is_a_conflict(client: TestClient, user_a: ApiUser):
    response = client.post(
        "/api/v1/categories", json={"name": "groceries", "kind": "expense"}, headers=user_a.headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "category.name_taken"


def test_rename_to_an_existing_name_is_a_conflict(client: TestClient, user_a: ApiUser):
    fuel = by_name(client, user_a, "Fuel")
    response = client.patch(
        f"/api/v1/categories/{fuel['id']}", json={"name": "Rent"}, headers=user_a.headers
    )
    assert response.status_code == 409


def test_rename_and_archive(client: TestClient, user_a: ApiUser):
    fuel = by_name(client, user_a, "Fuel")
    url = f"/api/v1/categories/{fuel['id']}"
    assert client.patch(url, json={"name": "Petrol"}, headers=user_a.headers).json()["name"] == (
        "Petrol"
    )
    assert client.patch(url, json={"is_archived": True}, headers=user_a.headers).status_code == 200
    assert "Petrol" not in {c["name"] for c in categories(client, user_a)}
    assert "Petrol" in {c["name"] for c in categories(client, user_a, include_archived=True)}
    assert client.patch(url, json={"is_archived": False}, headers=user_a.headers).status_code == 200


def test_uncategorized_cannot_be_archived_or_renamed(client: TestClient, user_a: ApiUser):
    uncategorized = by_name(client, user_a, "Uncategorized")
    url = f"/api/v1/categories/{uncategorized['id']}"
    for body in ({"is_archived": True}, {"name": "Misc"}):
        response = client.patch(url, json=body, headers=user_a.headers)
        assert response.status_code == 409
        assert response.json()["code"] == "category.protected"
    # Sending its current name or un-archiving is harmless.
    assert client.patch(
        url, json={"name": "Uncategorized"}, headers=user_a.headers
    ).status_code == (200)


def test_invalid_kind_is_rejected(client: TestClient, user_a: ApiUser):
    response = client.post(
        "/api/v1/categories", json={"name": "X", "kind": "transfer"}, headers=user_a.headers
    )
    assert response.status_code == 422
