"""User A's data is invisible to user B on every user-scoped route."""

import pytest
from fastapi.testclient import TestClient

from tests import isolation_registry  # noqa: F401  (registers every resource)
from tests.conftest import ApiUser
from tests.isolation import RESOURCES, IsolatedResource


def test_each_user_sees_only_their_own_identity(
    client: TestClient, user_a: ApiUser, user_b: ApiUser
):
    me_a = client.get("/api/v1/me", headers=user_a.headers).json()
    me_b = client.get("/api/v1/me", headers=user_b.headers).json()
    assert me_a["id"] == str(user_a.id) and me_a["email"] == user_a.email
    assert me_b["id"] == str(user_b.id) and me_b["email"] == user_b.email
    assert me_a["id"] != me_b["id"]


def _ids_in(payload: object) -> set[str]:
    """Every id value ("id" or any "*_id" key) anywhere in a JSON payload."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if (key == "id" or key.endswith("_id")) and isinstance(value, str):
                found.add(value)
            found |= _ids_in(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _ids_in(item)
    return found


@pytest.mark.parametrize("resource", RESOURCES, ids=[r.name for r in RESOURCES])
def test_user_b_cannot_see_or_change_user_a_resources(
    client: TestClient, user_a: ApiUser, user_b: ApiUser, resource: IsolatedResource
):
    resource_id = resource.create(client, user_a)

    if resource.detail:
        url = resource.detail.format(id=resource_id)
        before = client.get(url, headers=user_a.headers)
        assert before.status_code == 200
        response = client.get(url, headers=user_b.headers)
        assert response.status_code == 404, f"read {url}"
        assert resource_id not in response.text

    for method, template, body in resource.updates:
        url = template.format(id=resource_id)
        response = client.request(method, url, json=body, headers=user_b.headers)
        assert response.status_code == 404, f"{method} {url} -> {response.status_code}"
        assert resource_id not in response.text

    for method, template in resource.deletes:
        url = template.format(id=resource_id)
        response = client.request(method, url, headers=user_b.headers)
        assert response.status_code == 404, f"{method} {url} -> {response.status_code}"

    if resource.detail:
        after = client.get(resource.detail.format(id=resource_id), headers=user_a.headers)
        assert after.status_code == 200
        assert after.json() == before.json(), "user B's attempts changed user A's data"

    for list_url in resource.lists:
        own = client.get(list_url, headers=user_a.headers)
        other = client.get(list_url, headers=user_b.headers)
        assert own.status_code == 200 and other.status_code == 200, list_url
        assert resource_id in _ids_in(own.json()), f"{list_url} does not list A's own item"
        assert resource_id not in _ids_in(other.json()), f"{list_url} leaks A's item to B"
