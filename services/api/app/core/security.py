"""Access-token verification (handoff section 7.2).

Supabase Auth signs access tokens with an asymmetric key (ES256 or RS256) and
publishes the public keys as a JWKS document. We verify every token locally:

1. the header's ``alg`` must be one we allow (never HS256 or ``none``) and it
   must name a key id (``kid``);
2. the signature must verify with that public key;
3. ``iss``, ``aud``, ``exp``, ``iat`` (and ``nbf`` when present) must be valid,
   with 30 seconds of clock leeway;
4. ``sub`` must be a UUID.

Any failure gives the same 401 with no detail, so an attacker learns nothing
about why a forged token was rejected.

Development mode (``AUTH_MODE=dev``) uses a local key pair from ``.dev-keys/``
and goes through exactly the same checks.
"""

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import Settings

logger = logging.getLogger(__name__)

LEEWAY_SECONDS = 30
DEV_KEY_FILE = "dev-signing-key.pem"


class InvalidTokenError(Exception):
    """The token must be rejected with 401. The message is for logs only and never secret."""


class KeysUnavailableError(Exception):
    """The public keys could not be fetched (a server-side problem, not the client's)."""


@dataclass(frozen=True, slots=True)
class VerifiedClaims:
    subject: str
    email: str | None


class SigningKeyProvider(Protocol):
    def get_key(self, kid: str, algorithm: str) -> Any:
        """Return the public key for ``kid``, or raise ``InvalidTokenError``."""
        ...


class JwksKeyProvider:
    """Public keys from a JWKS URL, cached by PyJWT's client."""

    def __init__(self, jwks_url: str) -> None:
        # Keys are cached for 10 minutes; an unknown kid triggers one refresh.
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600, timeout=5)

    def get_key(self, kid: str, algorithm: str) -> Any:
        try:
            signing_key = self._client.get_signing_key(kid)
        except jwt.PyJWKClientConnectionError as exc:
            raise KeysUnavailableError("JWKS fetch failed") from exc
        except jwt.PyJWKClientError as exc:
            raise InvalidTokenError("unknown signing key") from exc
        # A key published for one algorithm must not verify another (algorithm confusion).
        if signing_key.algorithm_name and signing_key.algorithm_name != algorithm:
            raise InvalidTokenError("algorithm does not match key")
        return signing_key.key


class StaticKeyProvider:
    """Fixed public keys by kid. Used by dev mode and by tests."""

    def __init__(self, keys: dict[str, tuple[Any, str]]) -> None:
        self._keys = keys  # kid -> (public key, algorithm)

    def get_key(self, kid: str, algorithm: str) -> Any:
        entry = self._keys.get(kid)
        if entry is None:
            raise InvalidTokenError("unknown signing key")
        key, key_algorithm = entry
        if key_algorithm != algorithm:
            raise InvalidTokenError("algorithm does not match key")
        return key


class TokenVerifier:
    def __init__(
        self,
        keys: SigningKeyProvider,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._algorithms = algorithms

    def verify(self, token: str, now: datetime) -> VerifiedClaims:
        """Verify ``token`` as of ``now`` (the injected clock, so tests can freeze time)."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token") from exc

        algorithm = header.get("alg")
        kid = header.get("kid")
        if algorithm not in self._algorithms:
            raise InvalidTokenError("algorithm not allowed")
        if not isinstance(kid, str) or not kid:
            raise InvalidTokenError("missing key id")

        key = self._keys.get_key(kid, algorithm)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=LEEWAY_SECONDS,
                options={
                    "require": ["exp", "iat", "sub", "iss", "aud"],
                    "verify_signature": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    # Time claims are checked below against the injected clock.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(type(exc).__name__) from exc

        _check_time_claims(claims, now.timestamp())

        subject = claims.get("sub")
        try:
            uuid.UUID(str(subject))
        except ValueError as exc:
            raise InvalidTokenError("subject is not a UUID") from exc

        email = claims.get("email")
        return VerifiedClaims(
            subject=str(subject).lower(),
            email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
        )


def _numeric_claim(claims: dict[str, Any], name: str) -> int:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidTokenError(f"{name} is not a number")
    return int(value)


def _check_time_claims(claims: dict[str, Any], now: float) -> None:
    if now > _numeric_claim(claims, "exp") + LEEWAY_SECONDS:
        raise InvalidTokenError("ExpiredSignatureError")
    if _numeric_claim(claims, "iat") > now + LEEWAY_SECONDS:
        raise InvalidTokenError("issued in the future")
    if "nbf" in claims and _numeric_claim(claims, "nbf") > now + LEEWAY_SECONDS:
        raise InvalidTokenError("not yet valid")


# --- development keys ------------------------------------------------------------------


def key_id_for(public_key: ec.EllipticCurvePublicKey) -> str:
    der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()[:16]


def load_or_create_dev_key(directory: Path) -> ec.EllipticCurvePrivateKey:
    """The local ES256 key pair for AUTH_MODE=dev, created on first use. Never committed."""
    path = directory / DEV_KEY_FILE
    if path.exists():
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, ec.EllipticCurvePrivateKey):
            raise RuntimeError(f"{path} is not an EC private key")
        return loaded
    directory.mkdir(parents=True, exist_ok=True)
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    if os.name == "posix":
        path.chmod(0o600)
    logger.info("created development signing key")
    return private_key


def mint_token(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    subject: str,
    email: str,
    issuer: str,
    audience: str,
    now: datetime,
    lifetime: timedelta = timedelta(hours=24),
    extra_claims: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> str:
    """Sign an ES256 token shaped like a Supabase access token. Dev mode and tests only."""
    claims: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "iss": issuer,
        "aud": audience,
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    claims.update(extra_claims or {})
    token_headers = {"kid": key_id_for(private_key.public_key())}
    token_headers.update(headers or {})
    return jwt.encode(claims, private_key, algorithm="ES256", headers=token_headers)


def dev_subject_for(email: str) -> str:
    """The same email always maps to the same dev user id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finance-ai-dev:{email.strip().lower()}"))


def build_token_verifier(settings: Settings) -> TokenVerifier | None:
    """The verifier for the configured auth mode, or None if auth is not configured yet."""
    if settings.auth_mode == "dev":
        private_key = load_or_create_dev_key(settings.dev_keys_dir)
        public_key = private_key.public_key()
        provider: SigningKeyProvider = StaticKeyProvider(
            {key_id_for(public_key): (public_key, "ES256")}
        )
        return TokenVerifier(
            provider,
            issuer=settings.dev_issuer,
            audience=settings.auth_audience,
            algorithms=["ES256"],
        )
    if not settings.auth_jwks_url or not settings.auth_issuer:
        return None
    return TokenVerifier(
        JwksKeyProvider(settings.auth_jwks_url),
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        algorithms=settings.auth_algorithms,
    )
