"""Application configuration loaded from environment variables (and backend/.env locally)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Branding is centralised here (and in frontend/src/config/brand.ts).
    brand_name: str = "Agently"

    # Fail safe: forgetting to set it gets the production checks. Local .env sets development.
    environment: Literal["development", "test", "production"] = "production"
    log_level: str = "INFO"

    # SecretStr keeps the password out of reprs/logs. None = not configured.
    database_url: SecretStr | None = None
    database_connect_timeout_seconds: int = 3

    # Browser origins allowed to make state-changing requests (JSON list in the environment).
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Proxies in front of the backend that append to X-Forwarded-For. None/0 = ignore the header.
    # The Next.js /api rewrite does NOT append, so it never counts as a hop.
    trusted_proxy_hops: int | None = Field(default=None, ge=0)

    session_cookie_name: str = "agently_session"
    session_ttl_days: int = Field(default=14, gt=0)
    # None = Secure everywhere except development.
    session_cookie_secure: bool | None = None

    # Attempts above a limit get 429; accounts are never locked.
    login_window_minutes: int = Field(default=15, gt=0)
    login_limit_per_account_ip: int = Field(default=5, gt=0)
    login_limit_per_account: int = Field(default=50, gt=0)
    login_limit_per_ip: int = Field(default=20, gt=0)
    signup_window_minutes: int = Field(default=60, gt=0)
    signup_limit_per_ip: int = Field(default=5, gt=0)

    # Archived agents count. Lowering the limit only blocks new agents.
    agent_limit_per_workspace: int = Field(default=50, gt=0)
    # Create, edit and duplicate requests per user, across all workspaces.
    agent_write_limit: int = Field(default=60, gt=0)
    agent_write_window_minutes: int = Field(default=10, gt=0)

    # Agent and workspace writes: the wait for each lock, and idleness while holding locks.
    write_lock_timeout_seconds: int = Field(default=5, gt=0, le=3600)
    write_idle_timeout_seconds: int = Field(default=30, gt=0, le=3600)

    # Not env_ignore_empty: that would make an empty DATABASE_URL fall back to backend/.env.
    @field_validator("trusted_proxy_hops", "session_cookie_secure", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def session_cookie_is_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.environment != "development"

    def check_production_safety(self) -> None:
        """Refuse to start production with settings that silently weaken authentication."""
        if not self.is_production:
            return
        if not self.session_cookie_is_secure:
            raise RuntimeError("SESSION_COOKIE_SECURE must not be false in production")
        if self.trusted_proxy_hops is None:
            raise RuntimeError("TRUSTED_PROXY_HOPS must be set explicitly in production")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
