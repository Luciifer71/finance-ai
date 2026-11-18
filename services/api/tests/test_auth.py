"""M1: token verification, just-in-time provisioning, dev mode, 401 everywhere."""

import base64
import json
import logging
import re
import threading
import uuid
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    JwksKeyProvider,
    KeysUnavailableError,
    VerifiedClaims,
    dev_subject_for,
    key_id_for,
    load_or_create_dev_key,
    mint_token,
)
from app.domain.defaults import (
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    SEED_RULES,
)
from app.main import create_app
from app.models import CategorizationRule, Category, User
from app.services.users import get_or_provision_user
from app.tools import devtoken
from tests.conftest import TEST_AUDIENCE, TEST_ISSUER, ApiUser, TokenFactory

GENERIC_401 = {
    "type": "urn:finance-ai:problem:auth.unauthorized",
    "title": "Not authenticated",
    "status": 401,
    "detail": "A valid access token is required.",
    "code": "auth.unauthorized",
}


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _me(client: TestClient, token: str):
    return client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})


def assert_generic_401(response) -> None:
    assert response.status_code == 401
    body = response.json()
    body.pop("instance")
    assert body == GENERIC_401
    assert response.headers["www-authenticate"] == "Bearer"


# --- valid tokens and provisioning --------------------------------------------------------


def test_valid_token_returns_own_identity(client: TestClient, make_token: TokenFactory):
    subject = str(uuid.uuid4())
    response = _me(client, make_token(subject, "Krishay.Test@Example.TEST"))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "krishay.test@example.test"  # stored lower-case
    assert body["created_at"].endswith("Z")
    assert set(body) == {"id", "email", "created_at"}


def test_first_request_seeds_default_categories_and_rules(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    categories = db_session.scalars(select(Category).where(Category.user_id == user_a.id)).all()
    rules = db_session.scalars(
        select(CategorizationRule).where(CategorizationRule.user_id == user_a.id)
    ).all()

    # 17 expense + 4 income categories; 16 seed rules
    assert len(categories) == 21
    assert {c.name for c in categories if c.kind == "expense"} == set(DEFAULT_EXPENSE_CATEGORIES)
    assert {c.name for c in categories if c.kind == "income"} == set(DEFAULT_INCOME_CATEGORIES)
    assert {r.pattern for r in rules} == set(SEED_RULES)
    assert all(r.created_from == "seed" for r in rules)


def test_repeat_requests_do_not_duplicate_the_user(
    client: TestClient, user_a: ApiUser, db_session: Session
):
    for _ in range(3):
        assert _me(client, user_a.token).json()["id"] == str(user_a.id)
    count = db_session.scalar(
        select(func.count()).select_from(Category).where(Category.user_id == user_a.id)
    )
    assert count == 21


def test_email_used_by_another_identity_is_a_conflict(
    client: TestClient, make_token: TokenFactory, user_a: ApiUser
):
    response = _me(client, make_token(str(uuid.uuid4()), user_a.email.upper()))
    assert response.status_code == 409
    assert response.json()["code"] == "auth.email_in_use"


def test_token_without_email_cannot_create_a_user(client: TestClient, make_token: TokenFactory):
    response = _me(client, make_token(extra_claims={"email": None}))
    assert response.status_code == 401
    assert response.json()["code"] == "auth.email_required"


def test_concurrent_first_requests_create_exactly_one_user(engine: Engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    claims = VerifiedClaims(subject=str(uuid.uuid4()), email=f"race-{uuid.uuid4()}@example.test")
    barrier = threading.Barrier(4)
    results: list[uuid.UUID] = []
    errors: list[BaseException] = []

    def first_request() -> None:
        try:
            with factory() as session:
                barrier.wait()
                results.append(get_or_provision_user(session, claims).id)
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=first_request) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        with factory() as session:
            users = session.scalars(select(User).where(User.auth_subject == claims.subject)).all()
            categories = session.scalar(
                select(func.count()).select_from(Category).where(Category.user_id.in_(results))
            )
        assert errors == []
        assert len(users) == 1
        assert set(results) == {users[0].id}
        assert categories == 21
    finally:
        with factory() as session:
            ids = select(User.id).where(User.auth_subject == claims.subject)
            session.execute(delete(CategorizationRule).where(CategorizationRule.user_id.in_(ids)))
            session.execute(delete(Category).where(Category.user_id.in_(ids)))
            session.execute(delete(User).where(User.auth_subject == claims.subject))
            session.commit()


# --- rejected tokens ----------------------------------------------------------------------


def test_missing_or_malformed_header_is_401(client: TestClient):
    assert_generic_401(client.get("/api/v1/me"))
    assert_generic_401(client.get("/api/v1/me", headers={"Authorization": "Basic abc"}))
    assert_generic_401(client.get("/api/v1/me", headers={"Authorization": "Bearer "}))
    assert_generic_401(client.get("/api/v1/me", headers={"Authorization": "Bearer not.a.jwt"}))


def test_expired_token_is_rejected(client: TestClient, make_token: TokenFactory, clock: FixedClock):
    # Issued 2 h ago, valid 1 h: expired 1 h ago, far beyond the 30 s leeway.
    token = make_token(now=clock.now() - timedelta(hours=2), lifetime=timedelta(hours=1))
    assert_generic_401(_me(client, token))


def test_expiry_leeway_is_30_seconds(
    client: TestClient, make_token: TokenFactory, clock: FixedClock
):
    # exp = now - 20 s (inside leeway) is accepted; exp = now - 40 s is rejected.
    issued = clock.now() - timedelta(minutes=10)
    ok = make_token(now=issued, lifetime=timedelta(minutes=10) - timedelta(seconds=20))
    late = make_token(now=issued, lifetime=timedelta(minutes=10) - timedelta(seconds=40))
    assert _me(client, ok).status_code == 200
    assert_generic_401(_me(client, late))


def test_token_issued_in_the_future_is_rejected(
    client: TestClient, make_token: TokenFactory, clock: FixedClock
):
    assert_generic_401(_me(client, make_token(now=clock.now() + timedelta(minutes=5))))


def test_not_before_in_the_future_is_rejected(
    client: TestClient, make_token: TokenFactory, clock: FixedClock
):
    nbf = int((clock.now() + timedelta(minutes=5)).timestamp())
    assert_generic_401(_me(client, make_token(extra_claims={"nbf": nbf})))


def test_wrong_issuer_is_rejected(client: TestClient, make_token: TokenFactory):
    assert_generic_401(_me(client, make_token(issuer="https://evil.invalid/auth/v1")))


def test_wrong_audience_is_rejected(client: TestClient, make_token: TokenFactory):
    assert_generic_401(_me(client, make_token(audience="anon")))


def test_missing_expiry_with_valid_signature_is_rejected(
    client: TestClient, signing_key: ec.EllipticCurvePrivateKey, clock: FixedClock
):
    claims = {
        "sub": str(uuid.uuid4()),
        "email": "noexp@example.test",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "iat": int(clock.now().timestamp()),
    }
    token = jwt.encode(
        claims,
        signing_key,
        algorithm="ES256",
        headers={"kid": key_id_for(signing_key.public_key())},
    )
    assert_generic_401(_me(client, token))


def test_tampered_payload_is_rejected(client: TestClient, make_token: TokenFactory):
    token = make_token()
    header, _, signature = token.split(".")
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["sub"] = str(uuid.uuid4())  # try to become someone else
    assert_generic_401(_me(client, f"{header}.{_b64(claims)}.{signature}"))


def test_unsigned_token_is_rejected(
    client: TestClient, make_token: TokenFactory, signing_key: ec.EllipticCurvePrivateKey
):
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    kid = key_id_for(signing_key.public_key())
    unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT', 'kid': kid})}.{_b64(claims)}."
    assert_generic_401(_me(client, unsigned))


def test_hs256_token_is_rejected_even_with_a_known_kid(
    client: TestClient, make_token: TokenFactory, signing_key: ec.EllipticCurvePrivateKey
):
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    kid = key_id_for(signing_key.public_key())
    forged = jwt.encode(claims, "a-shared-secret-at-least-32-bytes!!", algorithm="HS256",
                        headers={"kid": kid})  # fmt: skip
    assert_generic_401(_me(client, forged))


def test_rs256_token_cannot_use_the_es256_key(
    client: TestClient, make_token: TokenFactory, signing_key: ec.EllipticCurvePrivateKey
):
    # RS256 is an allowed algorithm, but the kid names an ES256 key: algorithm confusion.
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        claims, rsa_key, algorithm="RS256", headers={"kid": key_id_for(signing_key.public_key())}
    )
    assert_generic_401(_me(client, forged))


def test_token_from_an_unknown_key_is_rejected(client: TestClient, make_token: TokenFactory):
    other_key = ec.generate_private_key(ec.SECP256R1())
    assert_generic_401(_me(client, make_token(key=other_key)))


def test_token_without_kid_is_rejected(
    client: TestClient, signing_key: ec.EllipticCurvePrivateKey, make_token: TokenFactory
):
    claims = jwt.decode(make_token(), options={"verify_signature": False})
    token = jwt.encode(claims, signing_key, algorithm="ES256")
    assert_generic_401(_me(client, token))


def test_subject_must_be_a_uuid(client: TestClient, make_token: TokenFactory):
    assert_generic_401(_me(client, make_token("not-a-uuid", "x@example.test")))


def test_non_numeric_expiry_is_rejected(
    client: TestClient, signing_key: ec.EllipticCurvePrivateKey, clock: FixedClock
):
    claims = {
        "sub": str(uuid.uuid4()),
        "email": "e@example.test",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "iat": int(clock.now().timestamp()),
        "exp": "tomorrow",
    }
    token = jwt.encode(
        claims,
        signing_key,
        algorithm="ES256",
        headers={"kid": key_id_for(signing_key.public_key())},
    )
    assert_generic_401(_me(client, token))


def test_tokens_never_appear_in_logs(
    client: TestClient, make_token: TokenFactory, caplog: pytest.LogCaptureFixture
):
    good = make_token()
    bad = make_token(audience="anon")
    with caplog.at_level(logging.DEBUG):
        _me(client, good)
        _me(client, bad)
    text = "\n".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    assert "auth_rejected" in text
    for token in (good, bad):
        for part in token.split("."):
            assert part not in text


# --- every /api/v1 route requires a token -------------------------------------------------


def api_operations(app: FastAPI) -> list[tuple[str, str]]:
    """Every (METHOD, path) under /api/v1, read from the OpenAPI spec."""
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in operations
    ]


def concrete_path(path: str) -> str:
    """Fill every {placeholder} with a random UUID."""
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def test_every_api_route_returns_401_without_a_token(app: FastAPI, client: TestClient):
    operations = api_operations(app)
    assert ("GET", "/api/v1/me") in operations
    for method, path in operations:
        response = client.request(method, concrete_path(path), json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.json()["code"] == "auth.unauthorized"


def test_openapi_marks_every_api_route_as_authenticated(app: FastAPI):
    # The contract must tell the mobile app which routes need a token.
    spec = app.openapi()
    for path, operations in spec["paths"].items():
        if path.startswith("/api/v1"):
            for operation in operations.values():
                assert operation.get("security") == [{"HTTPBearer": []}], path


# --- auth not configured / JWKS -------------------------------------------------------------


def test_missing_verifier_is_503(settings: Settings, db_session: Session):
    unconfigured = settings.model_copy(update={"auth_jwks_url": None})
    app = create_app(unconfigured)
    assert app.state.token_verifier is None
    response = TestClient(app).get("/api/v1/me", headers={"Authorization": "Bearer x.y.z"})
    assert response.status_code == 503
    assert response.json()["code"] == "auth.not_configured"


class _FakeJwkClient:
    def __init__(self, key: object = None, error: Exception | None = None) -> None:
        self.key = key
        self.error = error

    def get_signing_key(self, kid: str) -> object:
        if self.error:
            raise self.error
        return self.key


def _jwks_provider(fake: _FakeJwkClient) -> JwksKeyProvider:
    provider = JwksKeyProvider("https://auth.invalid/jwks.json")
    provider._client = fake  # type: ignore[assignment]  # no network in tests
    return provider


def test_jwks_provider_returns_matching_key():
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    jwk = jwt.PyJWK.from_dict(json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key)), "ES256")
    assert _jwks_provider(_FakeJwkClient(jwk)).get_key("kid", "ES256") is jwk.key


def test_jwks_provider_rejects_algorithm_mismatch():
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    jwk = jwt.PyJWK.from_dict(json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key)), "ES256")
    with pytest.raises(InvalidTokenError):
        _jwks_provider(_FakeJwkClient(jwk)).get_key("kid", "RS256")


def test_jwks_provider_unknown_kid_and_outage():
    with pytest.raises(InvalidTokenError):
        _jwks_provider(_FakeJwkClient(error=jwt.PyJWKClientError("nope"))).get_key("k", "ES256")
    with pytest.raises(KeysUnavailableError):
        _jwks_provider(_FakeJwkClient(error=jwt.PyJWKClientConnectionError("down"))).get_key(
            "k", "ES256"
        )


def test_jwks_outage_is_a_503_not_a_401(
    settings: Settings, clock: FixedClock, db_session: Session, make_token: TokenFactory
):
    from app.core.security import TokenVerifier

    verifier = TokenVerifier(
        _jwks_provider(_FakeJwkClient(error=jwt.PyJWKClientConnectionError("down"))),
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        algorithms=["ES256"],
    )
    app = create_app(settings, clock=clock, token_verifier=verifier)
    response = TestClient(app).get(
        "/api/v1/me", headers={"Authorization": f"Bearer {make_token()}"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "auth.keys_unavailable"


# --- development mode ---------------------------------------------------------------------


def test_dev_mode_signs_in_with_a_local_key(
    tmp_path: Path, test_database_url: str, db_session: Session
):
    from app.database import get_db

    dev = Settings(
        app_env="development",
        auth_mode="dev",
        dev_keys_dir=tmp_path,
        database_url=test_database_url,
    )
    app = create_app(dev)
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    key = load_or_create_dev_key(tmp_path)
    email = "dev.user@example.test"
    token = mint_token(
        key,
        subject=dev_subject_for(email),
        email=email,
        issuer=dev.dev_issuer,
        audience=dev.auth_audience,
        now=app.state.clock.now(),
    )

    response = TestClient(app).get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == email
    # The same key file is reused, not regenerated.
    assert key_id_for(load_or_create_dev_key(tmp_path).public_key()) == key_id_for(key.public_key())


def test_dev_subject_is_stable_per_email():
    assert dev_subject_for("A@Example.test") == dev_subject_for("a@example.test")
    assert dev_subject_for("a@example.test") != dev_subject_for("b@example.test")


def test_devtoken_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("DEV_KEYS_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "dev")
    assert devtoken.main(["a@example.test"]) == 0
    token = capsys.readouterr().out.strip()
    assert jwt.decode(token, options={"verify_signature": False})["sub"] == dev_subject_for(
        "a@example.test"
    )

    monkeypatch.setenv("AUTH_MODE", "jwks")
    assert devtoken.main(["a@example.test"]) == 1
    assert devtoken.main(["not-an-email"]) == 2


def test_dev_key_file_must_be_an_ec_key(tmp_path: Path):
    from cryptography.hazmat.primitives import serialization

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "dev-signing-key.pem").write_bytes(
        rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(RuntimeError, match="not an EC private key"):
        load_or_create_dev_key(tmp_path)
