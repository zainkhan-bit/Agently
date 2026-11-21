"""Shared fixtures: throwaway PostgreSQL databases and honest reporting of skipped DB tests.

Database tests are marked ``@pytest.mark.db``. They run against ``agently_test`` (created,
migrated to head, and dropped by this file) or, for migration tests, a fresh
``agently_migrations_scratch`` per test. The development database is never touched; see
``tests/db_utils.py`` for the name guard that enforces this.

When DATABASE_URL is unset (or empty), DB tests are skipped and the run ends with a loud
one-line summary so a skip is never mistaken for a pass.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests import db_utils

BACKEND_DIR = Path(__file__).resolve().parents[1]
SKIP_REASON = "DATABASE_URL not set"
_skipped_db_tests_key = pytest.StashKey[int]()


def configured_database_url() -> str | None:
    url = get_settings().database_url
    if url is None or not url.get_secret_value():
        return None
    return url.get_secret_value()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    db_items = [item for item in items if item.get_closest_marker("db")]
    config.stash[_skipped_db_tests_key] = 0
    if configured_database_url() is not None:
        return
    for item in db_items:
        item.add_marker(pytest.mark.skip(reason=SKIP_REASON))
    config.stash[_skipped_db_tests_key] = len(db_items)


def pytest_terminal_summary(terminalreporter, exitstatus, config: pytest.Config) -> None:
    skipped = config.stash.get(_skipped_db_tests_key, 0)
    if skipped:
        terminalreporter.write_line(
            f"{skipped} database tests SKIPPED: {SKIP_REASON}", red=True, bold=True
        )


def alembic_config(connection) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    return cfg


def migrate(engine: Engine, revision: str = "head") -> None:
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), revision)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = configured_database_url()
    if url is None:  # pragma: no cover - db tests are skipped at collection in this case
        pytest.skip(SKIP_REASON)
    return url


@pytest.fixture(scope="session")
def test_engine(database_url: str) -> Iterator[Engine]:
    """``agently_test``: recreated at session start, migrated to head, dropped at the end."""
    url = db_utils.recreate_database(database_url, db_utils.TEST_DATABASE_NAME)
    engine = create_engine(url)
    try:
        migrate(engine)
        yield engine
    finally:
        engine.dispose()
        db_utils.drop_database(database_url, db_utils.TEST_DATABASE_NAME)


@pytest.fixture
def db_session(test_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, even if the test commits."""
    connection = test_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def scratch_url(database_url: str) -> Iterator[URL]:
    """A brand-new empty database for one migration test."""
    url = db_utils.recreate_database(database_url, db_utils.SCRATCH_DATABASE_NAME)
    try:
        yield url
    finally:
        db_utils.drop_database(database_url, db_utils.SCRATCH_DATABASE_NAME)
