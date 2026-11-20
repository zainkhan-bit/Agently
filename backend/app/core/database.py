"""Database engine and connectivity checks."""

import logging
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when DATABASE_URL is not set."""


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not configured")
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )


def check_database() -> str:
    """Return 'ok', 'not_configured', or 'unavailable'. Never raises, never logs credentials."""
    try:
        engine = get_engine()
    except DatabaseNotConfiguredError:
        return "not_configured"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - readiness must report, not crash
        # Log only the exception type: driver messages can include host/user details.
        logger.warning("database readiness check failed: %s", type(exc).__name__)
        return "unavailable"
