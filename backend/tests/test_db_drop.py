"""Dropping a throwaway database: whose connections are ended, retries, and the final message."""

import pytest
from psycopg.errors import InsufficientPrivilege, ObjectInUse
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from tests import db_utils

NAME = "agently_scratch"


def list_processes(connection: Connection) -> None:
    """Replace pg_stat_activity for this transaction: temporary tables are found first."""
    connection.execute(
        text(
            "CREATE TEMP TABLE pg_stat_activity (pid int, datname text, backend_type text,"
            " usename text, application_name text) ON COMMIT DROP"
        )
    )
    connection.execute(
        text(
            "INSERT INTO pg_stat_activity VALUES"
            " (-1, :name, 'client backend', current_user, 'pytest'),"
            " (-2, :name, 'autovacuum worker', NULL, ''),"
            " (-3, :name, 'autovacuum worker', current_user, ''),"
            " (-4, :name, 'client backend', 'postgres', 'pgAdmin'),"
            " (-5, :name, NULL, 'postgres', 'hidden'),"
            " (-6, 'agently', 'client backend', current_user, 'dev server'),"
            " (pg_backend_pid(), :name, 'client backend', current_user, 'self')"
        ),
        {"name": NAME},
    )


@pytest.mark.db
def test_only_own_client_connections_to_that_database_are_ended(db_session: Session) -> None:
    connection = db_session.connection()
    list_processes(connection)
    assert db_utils.own_client_pids(connection, NAME) == [-1]


@pytest.mark.db
def test_holders_are_described(db_session: Session) -> None:
    connection = db_session.connection()
    list_processes(connection)
    described = db_utils.describe_holders(connection, NAME)
    assert "backend_type=client backend, usename=postgres, application_name=pgAdmin" in described
    assert "backend_type=autovacuum worker, usename=none, application_name=none" in described
    assert "backend_type=hidden, usename=postgres" in described
    assert "dev server" not in described


@pytest.mark.db
def test_an_open_connection_of_this_role_does_not_block_the_drop(database_url, scratch_url) -> None:
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as held:
            held.execute(text("SELECT 1"))
            db_utils.drop_database(database_url, scratch_url.database)
            held.invalidate()
    finally:
        engine.dispose()


class FakeConnection:
    """Fails the first DROPs with the given error."""

    def __init__(self, failures: int, error: Exception) -> None:
        self.failures, self.error, self.drops = failures, error, 0

    def scalars(self, *_):
        return []

    def execute(self, statement, *_):
        assert "FORCE" not in str(statement)
        self.drops += 1
        if self.drops <= self.failures:
            raise self.error


IN_USE = OperationalError("DROP", {}, ObjectInUse())


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(db_utils.time, "sleep", calls.append)
    return calls


def test_the_drop_is_retried_while_in_use(sleeps) -> None:
    connection = FakeConnection(4, IN_USE)
    db_utils.drop_with_retries(connection, NAME)
    assert connection.drops == 5
    assert sleeps == [0.5] * 4


def test_the_last_failure_names_the_holders(sleeps, monkeypatch) -> None:
    monkeypatch.setattr(db_utils, "describe_holders", lambda *_: "pid 7: the holder")
    connection = FakeConnection(5, IN_USE)
    with pytest.raises(db_utils.DatabaseInUseError, match="agently_scratch.*pid 7: the holder"):
        db_utils.drop_with_retries(connection, NAME)
    assert connection.drops == 5


def test_other_errors_are_not_retried(sleeps) -> None:
    connection = FakeConnection(1, ProgrammingError("DROP", {}, InsufficientPrivilege()))
    with pytest.raises(ProgrammingError):
        db_utils.drop_with_retries(connection, NAME)
    assert connection.drops == 1
