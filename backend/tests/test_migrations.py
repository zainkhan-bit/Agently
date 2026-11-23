"""Migrations: fresh database, rollback, re-upgrade, no drift, no leaked credentials."""

import os
import subprocess
import sys

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.models import Base
from tests.conftest import BACKEND_DIR, downgrade, migrate
from tests.db_utils import sibling_url

pytestmark = pytest.mark.db

IDENTITY_TABLES = {
    "users",
    "workspaces",
    "memberships",
    "sessions",
    "auth_throttle_events",
}


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_downgrade_upgrade_on_fresh_database(scratch_url) -> None:
    engine = create_engine(scratch_url)
    try:
        assert _tables(engine) == set()

        migrate(engine)
        assert _tables(engine) == IDENTITY_TABLES | {"alembic_version"}

        downgrade(engine)
        assert _tables(engine) & IDENTITY_TABLES == set()

        migrate(engine)
        assert _tables(engine) >= IDENTITY_TABLES
    finally:
        engine.dispose()


def test_migrations_match_models(scratch_url) -> None:
    engine = create_engine(scratch_url)
    try:
        migrate(engine)
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert diff == []
    finally:
        engine.dispose()


def test_migration_failure_does_not_print_password(database_url) -> None:
    secret = "wrong-pw-do-not-print-9f3a"
    bad_url = sibling_url(database_url, "agently").set(password=secret)
    env = {**os.environ, "DATABASE_URL": bad_url.render_as_string(hide_password=False)}
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "alembic", "current"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert secret not in result.stdout
    assert secret not in result.stderr
