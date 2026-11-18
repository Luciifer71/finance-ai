"""User-isolation harness (handoff M1).

Every user-scoped resource registers an ``IsolatedResource`` here. The test in
``test_isolation.py`` then proves, for each one, that user B:

- gets 404 (never 403, never the data) when reading A's resource by id,
- gets 404 when updating or deleting it, and A's resource is unchanged,
- never sees it in any list endpoint.

Later milestones add their resources to ``RESOURCES``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import ApiUser

Creator = Callable[[TestClient, ApiUser], str]


@dataclass(frozen=True)
class IsolatedResource:
    name: str
    create: Creator  # creates one resource as the given user, returns its id
    detail: str | None = None  # e.g. "/api/v1/accounts/{id}"
    updates: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    deletes: list[tuple[str, str]] = field(default_factory=list)
    lists: list[str] = field(default_factory=list)  # list endpoints with an "items" array


RESOURCES: list[IsolatedResource] = []


def register(resource: IsolatedResource) -> IsolatedResource:
    RESOURCES.append(resource)
    return resource
