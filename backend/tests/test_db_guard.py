"""The test suite must never be able to create or drop a non-disposable database."""

import pytest
from sqlalchemy.engine import make_url

from tests import db_utils

# Port 1 refuses connections: if a guard let a call through, we'd see a connection error instead.
UNREACHABLE = make_url("postgresql+psycopg://agently:pw@127.0.0.1:1/agently")


@pytest.mark.parametrize(
    "name", ["agently", "postgres", "test", "agently_test_backup", "my_test_db_prod", ""]
)
def test_guard_rejects_non_disposable_names(name: str) -> None:
    with pytest.raises(db_utils.UnsafeDatabaseNameError):
        db_utils.assert_disposable_name(name)


@pytest.mark.parametrize("name", ["agently_test", "agently_migrations_scratch"])
def test_guard_accepts_disposable_names(name: str) -> None:
    db_utils.assert_disposable_name(name)


@pytest.mark.parametrize("operation", [db_utils.drop_database, db_utils.recreate_database])
def test_dev_database_cannot_be_dropped_or_recreated(operation) -> None:
    # The guard must fire before any connection is attempted.
    with pytest.raises(db_utils.UnsafeDatabaseNameError):
        operation(UNREACHABLE, "agently")


@pytest.mark.parametrize(
    "base",
    [
        "postgresql+psycopg://u:p@localhost:5432/agently?dbname=agently",
        "postgresql+psycopg://u:p@localhost:5432/agently?DATABASE=agently&sslmode=disable",
    ],
)
def test_derived_url_cannot_be_redirected_by_query_parameters(base: str) -> None:
    # What the driver will actually connect to, not just what the URL path says.
    url = db_utils.sibling_url(base, db_utils.TEST_DATABASE_NAME)
    _, connect_kwargs = url.get_dialect()().create_connect_args(url)
    assert connect_kwargs["dbname"] == db_utils.TEST_DATABASE_NAME
    assert "database" not in {key.lower() for key in url.query}


def test_suite_database_names_are_disposable() -> None:
    db_utils.assert_disposable_name(db_utils.TEST_DATABASE_NAME)
    db_utils.assert_disposable_name(db_utils.SCRATCH_DATABASE_NAME)
