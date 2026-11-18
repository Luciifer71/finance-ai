"""M0 guardrails: problem details, request ids, logging, body limits, config, clock."""

import io
import json
import logging
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.core.clock import FixedClock, SystemClock
from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.logging import (
    REDACTED,
    AppLogHandler,
    configure_logging,
    redact_text,
    redact_value,
)
from app.main import create_app

# Built at runtime so secret scanners do not mistake the fixture for a real token.
SECRET_TOKEN = ".".join(["eyJhbGciOiJFUzI1NiJ9", "eyJzdWIiOiJ4In0", "c2lnbmF0dXJl"])


class Payload(BaseModel):
    amount: int


def _app_with_test_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    def boom() -> None:
        raise ProblemError(409, "demo.conflict", "Conflict", "Something conflicts.")

    def crash() -> None:
        raise RuntimeError("SELECT * FROM secret_table WHERE account = 123456789")

    def echo(payload: Payload) -> dict[str, int]:
        return {"amount": payload.amount}

    app.add_api_route("/api/v1/_test/problem", boom)
    app.add_api_route("/api/v1/_test/crash", crash)
    app.add_api_route("/api/v1/_test/echo", echo, methods=["POST"])
    return app


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(_app_with_test_routes(settings), raise_server_exceptions=False)


# --- problem details ------------------------------------------------------------


def test_problem_error_becomes_rfc9457_problem(client: TestClient):
    response = client.get("/api/v1/_test/problem", headers={"X-Request-ID": "req-1"})

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "urn:finance-ai:problem:demo.conflict",
        "title": "Conflict",
        "status": 409,
        "detail": "Something conflicts.",
        "instance": "urn:finance-ai:request:req-1",
        "code": "demo.conflict",
    }


def test_unknown_route_is_a_404_problem(client: TestClient):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"


def test_validation_error_lists_fields_without_echoing_input(client: TestClient):
    response = client.post("/api/v1/_test/echo", json={"amount": "not-a-number-998877"})

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "request.validation_failed"
    assert body["errors"][0]["field"] == "amount"
    assert "998877" not in response.text


def test_unhandled_error_hides_internals(client: TestClient):
    response = client.get("/api/v1/_test/crash")

    assert response.status_code == 500
    assert response.json()["code"] == "server.error"
    assert "secret_table" not in response.text
    assert "Traceback" not in response.text


# --- request id and headers -------------------------------------------------------


def test_request_id_is_echoed_when_valid(client: TestClient):
    response = client.get("/health", headers={"X-Request-ID": "abc.DEF-123_x"})
    assert response.headers["x-request-id"] == "abc.DEF-123_x"


def test_invalid_request_id_is_replaced(client: TestClient):
    response = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert response.headers["x-request-id"] != "bad id with spaces"
    assert len(response.headers["x-request-id"]) == 32


def test_api_responses_carry_security_headers(client: TestClient):
    response = client.get("/api/v1/_test/problem")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


# --- body size limit ---------------------------------------------------------------


def test_body_over_limit_is_rejected_with_413(settings: Settings):
    small = settings.model_copy(update={"max_body_bytes": 100})
    client = TestClient(_app_with_test_routes(small))

    response = client.post(
        "/api/v1/_test/echo",
        content=json.dumps({"amount": 1, "pad": "x" * 200}),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "request.too_large"


def test_streamed_body_over_limit_is_rejected_with_413(settings: Settings):
    small = settings.model_copy(update={"max_body_bytes": 100})
    client = TestClient(_app_with_test_routes(small))

    def chunks():
        yield b'{"amount": 1, "pad": "'
        yield b"x" * 200
        yield b'"}'

    # A generator body has no Content-Length, so only the streaming check can catch it.
    response = client.post(
        "/api/v1/_test/echo", content=chunks(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 413


def test_body_under_limit_is_accepted(client: TestClient):
    response = client.post("/api/v1/_test/echo", json={"amount": 5})
    assert response.status_code == 200
    assert response.json() == {"amount": 5}


# --- logging -----------------------------------------------------------------------


def test_logs_never_contain_the_authorization_header(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    stream = io.StringIO()
    handler = AppLogHandler()
    handler.setStream(stream)
    logging.getLogger().addHandler(handler)
    try:
        with caplog.at_level(logging.DEBUG):
            client.get("/health", headers={"Authorization": f"Bearer {SECRET_TOKEN}"})
            client.get("/api/v1/_test/crash", headers={"Authorization": f"Bearer {SECRET_TOKEN}"})
    finally:
        logging.getLogger().removeHandler(handler)

    captured = stream.getvalue() + "\n".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    assert "request" in captured  # the access log line was written
    assert SECRET_TOKEN not in captured
    assert "Bearer" not in captured


def test_access_log_uses_path_template_and_json(settings: Settings):
    app = create_app(settings)

    def item(item_id: str) -> dict[str, str]:
        return {"ok": "yes"}

    app.add_api_route("/api/v1/_test/items/{item_id}", item)
    stream = io.StringIO()
    handler = AppLogHandler()
    handler.setStream(stream)
    access = logging.getLogger("app.access")
    access.addHandler(handler)
    try:
        TestClient(app).get("/api/v1/_test/items/12345678", headers={"X-Request-ID": "r-42"})
    finally:
        access.removeHandler(handler)

    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["msg"] == "request"
    assert line["path"] == "/api/v1/_test/items/{item_id}"
    assert line["status"] == 200
    assert line["request_id"] == "r-42"
    assert "12345678" not in stream.getvalue()


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        (f"Authorization: Bearer {SECRET_TOKEN}", SECRET_TOKEN),
        (f"token={SECRET_TOKEN}", SECRET_TOKEN),
        ('{"password": "hunter2"}', "hunter2"),
        ("account 123456789012 debited", "123456789012"),
        (f"jwt {SECRET_TOKEN} seen", SECRET_TOKEN),
    ],
)
def test_redaction_removes_secrets(raw: str, must_not_contain: str):
    cleaned = redact_text(raw)
    assert must_not_contain not in cleaned
    assert REDACTED in cleaned


def test_redaction_of_structured_values():
    value = {"authorization": "x", "nested": {"note": "acct 9876543210"}, "items": ["ok"]}
    assert redact_value("extra", value) == {
        "authorization": REDACTED,
        "nested": {"note": f"acct {REDACTED}"},
        "items": ["ok"],
    }


def test_redacting_handler_scrubs_extra_fields():
    stream = io.StringIO()
    handler = AppLogHandler()
    handler.setStream(stream)
    logger = logging.getLogger("tests.redaction")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning("saw %s", "card 4111111111111111", extra={"token": SECRET_TOKEN})
    finally:
        logger.removeHandler(handler)
        logger.propagate = True

    output = stream.getvalue()
    assert "4111111111111111" not in output
    assert SECRET_TOKEN not in output
    assert json.loads(output)["token"] == REDACTED


def test_configure_logging_is_idempotent():
    configure_logging("INFO")
    configure_logging("INFO")
    ours = [h for h in logging.getLogger().handlers if isinstance(h, AppLogHandler)]
    assert len(ours) == 1


# --- configuration -----------------------------------------------------------------


def test_dev_auth_refuses_to_start_outside_development():
    with pytest.raises(RuntimeError, match="AUTH_MODE=dev"):
        create_app(Settings(app_env="production", auth_mode="dev"))
    with pytest.raises(RuntimeError, match="AUTH_MODE=dev"):
        create_app(Settings(app_env="test", auth_mode="dev"))


def test_production_requires_jwks_settings_and_database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_JWKS_URL"):
        create_app(Settings(app_env="production"))
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(
            Settings(
                app_env="production",
                auth_jwks_url="https://x.invalid/jwks",
                auth_issuer="https://x.invalid",
                database_url=None,
            )
        )


def test_lists_are_read_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://127.0.0.1:8081, http://localhost:19006")
    monkeypatch.setenv("AUTH_ALGORITHMS", "ES256")
    settings = Settings()
    assert settings.cors_allow_origins == ["http://127.0.0.1:8081", "http://localhost:19006"]
    assert settings.auth_algorithms == ["ES256"]


@pytest.mark.parametrize("algorithms", ["HS256", "none", "ES256,HS256", ""])
def test_symmetric_or_unsigned_algorithms_are_refused(algorithms: str):
    with pytest.raises(ValidationError):
        Settings(auth_algorithms=algorithms)


def test_docs_are_only_served_in_development(settings: Settings):
    assert TestClient(create_app(settings)).get("/docs").status_code == 404
    dev = settings.model_copy(update={"app_env": "development"})
    assert TestClient(create_app(dev)).get("/docs").status_code == 200


def test_cors_allows_only_configured_origins(settings: Settings):
    configured = settings.model_copy(update={"cors_allow_origins": ["http://127.0.0.1:8081"]})
    client = TestClient(create_app(configured))

    allowed = client.get("/health", headers={"Origin": "http://127.0.0.1:8081"})
    denied = client.get("/health", headers={"Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:8081"
    assert "access-control-allow-origin" not in denied.headers


# --- clock -------------------------------------------------------------------------


def test_reporting_date_uses_india_time():
    # 20:00 UTC on 30 Nov is 01:30 IST on 1 Dec.
    clock = FixedClock(datetime(2026, 11, 30, 20, 0, tzinfo=UTC))
    assert clock.today() == date(2026, 12, 1)
    assert clock.now().tzinfo == UTC


def test_fixed_clock_needs_timezone():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 11, 30, 20, 0))  # noqa: DTZ001 - deliberately naive to test the guard


def test_system_clock_is_timezone_aware():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert isinstance(SystemClock().today(), date)
