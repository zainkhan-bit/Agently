"""Helpers for the throwaway PostgreSQL databases the test suite creates and drops.

Safety: every create/drop goes through ``assert_disposable_name`` first, so the suite can
only ever touch databases whose names end in ``_test`` or ``_scratch``. The development
database (``agently``) can never be dropped from here.
"""

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_NAME = "agently_test"
SCRATCH_DATABASE_NAME = "agently_migrations_scratch"
DISPOSABLE_SUFFIXES = ("_test", "_scratch")
MAINTENANCE_DATABASE = "postgres"


class UnsafeDatabaseNameError(RuntimeError):
    """Raised when test code tries to create or drop a non-disposable database."""


def assert_disposable_name(name: str) -> None:
    if not name or not name.endswith(DISPOSABLE_SUFFIXES):
        raise UnsafeDatabaseNameError(
            f"refusing to create or drop database {name!r}: "
            f"only names ending in {' or '.join(DISPOSABLE_SUFFIXES)} are disposable"
        )
    # Names are interpolated into DDL (identifiers cannot be bound), so allow only safe characters.
    if not name.replace("_", "").isalnum():
        raise UnsafeDatabaseNameError(f"refusing database name with unsafe characters: {name!r}")


def sibling_url(base_url: str | URL, database: str) -> URL:
    """Same server and credentials as ``base_url``, different database."""
    return make_url(base_url).set(database=database)


def _maintenance_engine(base_url: str | URL):
    return create_engine(
        sibling_url(base_url, MAINTENANCE_DATABASE),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )


def drop_database(base_url: str | URL, name: str) -> None:
    assert_disposable_name(name)
    engine = _maintenance_engine(base_url)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def recreate_database(base_url: str | URL, name: str) -> URL:
    """Drop (if left over from a crashed run) and create ``name``; return its URL."""
    assert_disposable_name(name)
    drop_database(base_url, name)
    engine = _maintenance_engine(base_url)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()
    return sibling_url(base_url, name)
