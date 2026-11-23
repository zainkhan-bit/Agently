"""Database engine, ORM base, request-scoped sessions, and connectivity checks."""

import logging
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Stable constraint names so Alembic autogenerate and downgrades refer to predictable names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when DATABASE_URL is not set."""


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if settings.database_url is None or not settings.database_url.get_secret_value():
        raise DatabaseNotConfiguredError("DATABASE_URL is not configured")
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        # Logged errors must not carry emails, password hashes or token hashes.
        hide_parameters=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Never commits on its own; service code commits explicitly. Anything left uncommitted is
    rolled back when the session closes, and an exception triggers an explicit rollback.
    """
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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
