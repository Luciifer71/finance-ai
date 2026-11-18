"""Authentication dependency shared by every /api/v1 route."""

import hashlib
import logging
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.core.logging import set_user_hash
from app.core.security import InvalidTokenError, KeysUnavailableError, TokenVerifier
from app.database import get_db
from app.models import User
from app.services.users import get_or_provision_user

logger = logging.getLogger(__name__)


def _unauthorized() -> ProblemError:
    # One generic answer for every reason, so a rejected token reveals nothing.
    return ProblemError(
        401,
        "auth.unauthorized",
        "Not authenticated",
        "A valid access token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Declares "Authorization: Bearer <JWT>" in the OpenAPI contract. auto_error=False so a
# missing header gets our own problem response instead of FastAPI's default.
bearer_scheme = HTTPBearer(auto_error=False)


def user_hash(user_id: object) -> str:
    """A short, non-reversible id for logs, so log lines never carry the real user id."""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    verifier: TokenVerifier | None = request.app.state.token_verifier
    token = credentials.credentials.strip() if credentials else ""
    if not token:
        raise _unauthorized()
    if verifier is None:
        raise ProblemError(503, "auth.not_configured", "Authentication not configured")
    try:
        claims = verifier.verify(token, request.app.state.clock.now())
    except InvalidTokenError as exc:
        # The reason is a fixed internal label (e.g. "ExpiredSignatureError"), never token data.
        logger.info("auth_rejected", extra={"reason": str(exc)})
        raise _unauthorized() from None
    except KeysUnavailableError:
        logger.warning("auth_keys_unavailable")
        raise ProblemError(
            503, "auth.keys_unavailable", "Authentication temporarily unavailable"
        ) from None

    user = get_or_provision_user(session, claims)
    set_user_hash(user_hash(user.id))
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
