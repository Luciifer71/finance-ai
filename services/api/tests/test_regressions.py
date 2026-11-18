"""Regressions found while trying the API by hand in /docs."""

import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import AppLogHandler
from app.main import create_app
from tests.conftest import ApiUser


def test_access_log_shows_full_template_for_router_routes(app: FastAPI, user_a: ApiUser):
    client = TestClient(app)
    stream = io.StringIO()
    handler = AppLogHandler()
    handler.setStream(stream)
    access = logging.getLogger("app.access")
    access.addHandler(handler)
    try:
        client.get(
            "/api/v1/accounts/00000000-0000-0000-0000-000000000000",
            headers={**user_a.headers, "X-Request-ID": "0123456789abcdef0123456789abcdef"},
        )
    finally:
        access.removeHandler(handler)
    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["path"] == "/api/v1/accounts/{account_id}"
    # Our own request id has 10 digits in a row, but it is not user data: never redacted.
    assert line["request_id"] == "0123456789abcdef0123456789abcdef"


def test_openapi_documents_the_real_error_shape(settings: Settings):
    spec = create_app(settings).openapi()
    responses = spec["paths"]["/api/v1/accounts"]["post"]["responses"]
    assert responses["422"]["content"] == {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/ValidationProblem"}}
    }
    assert "401" in responses
    assert "HTTPValidationError" not in spec["components"]["schemas"]
