"""Helpers for the throwaway PostgreSQL databases the test suite creates and drops.

Safety: every create/drop goes through ``assert_disposable_name`` first, so the suite can
only ever touch databases whose names end in ``_test`` or ``_scratch``. The development
database (``agently``) can never be dropped from here.
"""

import time

from psycopg.errors import ObjectInUse
from sqlalchemy import URL, Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

TEST_DATABASE_NAME = "agently_test"
SCRATCH_DATABASE_NAME = "agently_migrations_scratch"
DISPOSABLE_SUFFIXES = ("_test", "_scratch")
MAINTENANCE_DATABASE = "postgres"
DROP_TRIES = 5
DROP_RETRY_SECONDS = 0.5

# Not DROP ... WITH (FORCE): that also tries to terminate processes of other roles, such as an
# autovacuum worker, and then fails with "permission denied". A plain DROP stops autovacuum itself.
OWN_CLIENTS = text(
    "SELECT pid FROM pg_stat_activity WHERE datname = :name"
    " AND backend_type = 'client backend' AND usename = current_user AND pid <> pg_backend_pid()"
)
# backend_type is hidden (NULL) for other roles' processes.
HOLDERS = text(
    "SELECT pid, backend_type, usename, application_name FROM pg_stat_activity"
    " WHERE datname = :name ORDER BY pid"
)


class DatabaseInUseError(RuntimeError):
    """Raised when a throwaway database is still in use after every attempt to drop it."""


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
    """Same server and credentials as ``base_url``, different database.

    psycopg lets a ``?dbname=`` (or ``?database=``) query parameter override the path's
    database name, so those keys are stripped: otherwise a URL like ``.../agently?dbname=agently``
    would point the "throwaway" test engines at the real development database.
    """
    url = make_url(base_url)
    url = url.difference_update_query(
        [key for key in url.query if key.lower() in {"dbname", "database"}]
    )
    return url.set(database=database)


def _maintenance_engine(base_url: str | URL):
    return create_engine(
        sibling_url(base_url, MAINTENANCE_DATABASE),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )


def own_client_pids(connection: Connection, name: str) -> list[int]:
    return list(connection.scalars(OWN_CLIENTS, {"name": name}))


def describe_holders(connection: Connection, name: str) -> str:
    holders = [
        f"pid {row.pid}: backend_type={row.backend_type or 'hidden'},"
        f" usename={row.usename or 'none'}, application_name={row.application_name or 'none'}"
        for row in connection.execute(HOLDERS, {"name": name})
    ]
    return "; ".join(holders) or "no process is listed any more"


def drop_with_retries(connection: Connection, name: str) -> None:
    assert_disposable_name(name)
    for attempt in range(1, DROP_TRIES + 1):
        for pid in own_client_pids(connection, name):
            connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        try:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            return
        except DBAPIError as error:
            if not isinstance(error.orig, ObjectInUse):
                raise
            if attempt == DROP_TRIES:
                raise DatabaseInUseError(
                    f"could not drop {name!r} after {DROP_TRIES} tries, it is still in use by "
                    + describe_holders(connection, name)
                ) from error
        time.sleep(DROP_RETRY_SECONDS)


def drop_database(base_url: str | URL, name: str) -> None:
    assert_disposable_name(name)
    engine = _maintenance_engine(base_url)
    try:
        with engine.connect() as connection:
            drop_with_retries(connection, name)
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
