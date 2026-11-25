"""Application configuration loaded from environment variables (and backend/.env locally)."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.providers.models import GEMINI_MODELS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # A refused value may be a secret, and startup errors are logged.
        hide_input_in_errors=True,
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

    # Conversations are private to one person. Lowering a limit only blocks new ones.
    conversation_limit_per_agent: int = Field(default=200, gt=0)
    conversation_create_limit: int = Field(default=30, gt=0)
    conversation_create_window_minutes: int = Field(default=60, gt=0)
    message_limit_per_conversation: int = Field(default=500, gt=0)
    user_message_max_characters: int = Field(default=8_000, gt=0)
    assistant_message_max_characters: int = Field(default=32_000, gt=0)

    # Messages sent to agents, repeats included.
    message_send_limit_per_user: int = Field(default=60, gt=0)
    message_send_limit_per_workspace: int = Field(default=200, gt=0)
    message_send_window_minutes: int = Field(default=60, gt=0)
    # How much of a conversation an answer sees, and how long the answer may be.
    runtime_history_messages: int = Field(default=20, ge=0, le=200)
    runtime_input_token_budget: int = Field(default=32_000, gt=0, le=200_000)
    runtime_max_output_tokens: int = Field(default=4_000, gt=0, le=65_536)

    # Agent and workspace writes: the wait for each lock, and idleness while holding locks.
    write_lock_timeout_seconds: int = Field(default=5, gt=0, le=3600)
    write_idle_timeout_seconds: int = Field(default=30, gt=0, le=3600)

    # None = no AI features. The mock is not an AI and never runs in production.
    model_provider: Literal["mock", "gemini"] | None = None
    mock_provider_scenario: Literal[
        "ok",
        "timeout",
        "rate_limited",
        "unavailable",
        "refused",
        "malformed",
        "slow",
        "extra_field",
    ] = "ok"
    # Next.js gives up on a proxied request after 30 seconds.
    provider_timeout_seconds: int = Field(default=20, gt=0, le=25)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    # What people are told depends on it. Google uses and reviews what the free tier receives.
    gemini_tier: Literal["free", "paid"] = "free"
    # All real provider calls together, in US dollars: the last 24 hours and the last 30 days.
    provider_spend_limit_daily: Decimal = Field(default=Decimal(1), gt=0, le=100_000)
    provider_spend_limit_monthly: Decimal = Field(default=Decimal(10), gt=0, le=100_000)
    generation_limit_per_user: int = Field(default=10, gt=0)
    generation_limit_per_workspace: int = Field(default=30, gt=0)
    generation_window_minutes: int = Field(default=60, gt=0)

    # Not env_ignore_empty: that would make an empty DATABASE_URL fall back to backend/.env.
    @field_validator(
        "trusted_proxy_hops",
        "session_cookie_secure",
        "model_provider",
        "gemini_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def session_cookie_is_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.environment != "development"

    def check_gemini(self) -> str:
        """The key, or a startup error that never repeats it."""
        key = self.gemini_api_key.get_secret_value() if self.gemini_api_key else ""
        if not key:
            raise RuntimeError("GEMINI_API_KEY must be set when MODEL_PROVIDER is gemini")
        if not all("!" <= character <= "~" for character in key):
            raise RuntimeError("GEMINI_API_KEY holds characters that a key cannot have")
        if self.gemini_model not in GEMINI_MODELS:
            raise RuntimeError(f"GEMINI_MODEL must be one of: {', '.join(GEMINI_MODELS)}")
        if self.is_production and self.gemini_tier == "free":
            raise RuntimeError("GEMINI_TIER must not be free in production")
        return key

    def check_production_safety(self) -> None:
        """Refuse to start production with settings that silently weaken authentication."""
        if not self.is_production:
            return
        if not self.session_cookie_is_secure:
            raise RuntimeError("SESSION_COOKIE_SECURE must not be false in production")
        if self.trusted_proxy_hops is None:
            raise RuntimeError("TRUSTED_PROXY_HOPS must be set explicitly in production")
        if self.model_provider == "mock":
            raise RuntimeError("MODEL_PROVIDER must not be mock in production")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
