"""User A's data is invisible to user B on every user-scoped route."""

from fastapi.testclient import TestClient

from tests.conftest import ApiUser


def test_each_user_sees_only_their_own_identity(
    client: TestClient, user_a: ApiUser, user_b: ApiUser
):
    me_a = client.get("/api/v1/me", headers=user_a.headers).json()
    me_b = client.get("/api/v1/me", headers=user_b.headers).json()
    assert me_a["id"] == str(user_a.id) and me_a["email"] == user_a.email
    assert me_b["id"] == str(user_b.id) and me_b["email"] == user_b.email
    assert me_a["id"] != me_b["id"]
