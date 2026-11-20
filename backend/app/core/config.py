"""Application configuration loaded from environment variables (and backend/.env locally)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Branding is centralised here (and in frontend/src/config/brand.ts).
    brand_name: str = "Agently"

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # SecretStr keeps the password out of reprs/logs. None = not configured.
    database_url: SecretStr | None = None
    database_connect_timeout_seconds: int = 3

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
