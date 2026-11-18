"""Typed configuration read from environment variables.

Every setting has a safe default for local development except the secrets and
URLs that only the operator knows. Production refuses to start with settings
that would be unsafe there (see ``Settings.validate_for_startup``).
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# services/api/app/core/config.py -> services/api
API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]

AppEnv = Literal["development", "test", "production"]
AuthMode = Literal["jwks", "dev"]


def _split_csv(value: object) -> object:
    """Allow ``A,B,C`` in an environment variable for list settings."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    app_env: AppEnv = "development"
    database_url: str | None = None
    log_level: str = "INFO"

    # --- authentication (section 7.2 of the handoff) ---------------------
    auth_mode: AuthMode = "jwks"
    auth_jwks_url: str | None = None
    auth_issuer: str | None = None
    auth_audience: str = "authenticated"
    auth_algorithms: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["ES256", "RS256"]
    )
    # Where `AUTH_MODE=dev` keeps its local signing key pair. Ignored by Git.
    dev_keys_dir: Path = REPO_ROOT / ".dev-keys"
    dev_issuer: str = "finance-ai-dev"

    # --- HTTP -------------------------------------------------------------
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    max_body_bytes: int = 1_000_000

    # --- imports (section 8.1) -------------------------------------------
    max_upload_bytes: int = 5 * 1024 * 1024
    max_import_rows: int = 20_000

    # --- rate limits (section 12), requests per window -----------------------
    rate_limit_enabled: bool = True
    rate_limit_general_per_minute: int = 120
    rate_limit_imports_per_hour: int = 10
    rate_limit_exports_per_hour: int = 5
    rate_limit_assistant_per_hour: int = 30
    rate_limit_public_per_minute: int = 60

    @field_validator("auth_algorithms", "cors_allow_origins", mode="before")
    @classmethod
    def _parse_lists(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("auth_algorithms")
    @classmethod
    def _only_asymmetric_algorithms(cls, value: list[str]) -> list[str]:
        """Symmetric (HS*) and unsigned tokens are never accepted."""
        allowed = {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "PS256", "EdDSA"}
        bad = [alg for alg in value if alg not in allowed]
        if bad or not value:
            raise ValueError(f"unsupported JWT algorithms: {bad or 'none given'}")
        return value

    @property
    def docs_enabled(self) -> bool:
        return self.app_env == "development"

    def validate_for_startup(self) -> None:
        """Refuse configurations that would be unsafe. Called by ``create_app``."""
        if self.auth_mode == "dev" and self.app_env != "development":
            raise RuntimeError("AUTH_MODE=dev is only allowed when APP_ENV=development")
        if self.app_env == "production":
            if self.auth_mode != "jwks" or not self.auth_jwks_url or not self.auth_issuer:
                raise RuntimeError(
                    "Production requires AUTH_MODE=jwks with AUTH_JWKS_URL and AUTH_ISSUER"
                )
            if not self.database_url:
                raise RuntimeError("Production requires DATABASE_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings from the process environment (cached for the process)."""
    return Settings()
