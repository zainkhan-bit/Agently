"""Migrations: fresh database, rollback, re-upgrade, no drift, no leaked credentials."""

import os
import subprocess
import sys

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.models import Base
from tests.conftest import BACKEND_DIR, downgrade, migrate
from tests.db_utils import sibling_url

pytestmark = pytest.mark.db

APP_TABLES = {
    "users",
    "workspaces",
    "memberships",
    "sessions",
    "auth_throttle_events",
    "agents",
    "agent_versions",
    "provider_spend",
    "conversations",
    "messages",
    "executions",
    "knowledge_sources",
    "knowledge_chunks",
    "jobs",
}


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_downgrade_upgrade_on_fresh_database(scratch_url) -> None:
    engine = create_engine(scratch_url)
    try:
        assert _tables(engine) == set()

        migrate(engine)
        assert _tables(engine) == APP_TABLES | {"alembic_version"}

        downgrade(engine)
        assert _tables(engine) & APP_TABLES == set()

        migrate(engine)
        assert _tables(engine) >= APP_TABLES
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


def _insert_chunk(connection, content: str) -> None:
    """One chunk with the rows it depends on, written as plain SQL at revision 0010."""
    workspace = connection.execute(
        text("INSERT INTO workspaces (name) VALUES ('w') RETURNING id")
    ).scalar_one()
    agent = connection.execute(
        text(
            "INSERT INTO agents (workspace_id, status, current_version) "
            "VALUES (:w, 'active', 1) RETURNING id"
        ),
        {"w": workspace},
    ).scalar_one()
    source = connection.execute(
        text(
            "INSERT INTO knowledge_sources "
            "(workspace_id, agent_id, name, kind, size_bytes, sha256, storage_name, status) "
            "VALUES (:w, :a, 'f.txt', 'txt', 1, repeat('a', 64), repeat('b', 32), 'ready') "
            "RETURNING id"
        ),
        {"w": workspace, "a": agent},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO knowledge_chunks (source_id, workspace_id, agent_id, sequence, content) "
            "VALUES (:s, :w, :a, 0, :c)"
        ),
        {"s": source, "w": workspace, "a": agent, "c": content},
    )


def _search_columns(engine) -> list[tuple[str, str, str]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT content, search_english::text, search_simple::text "
                    "FROM knowledge_chunks"
                )
            )
        ]


def test_chunks_written_before_the_search_columns_become_searchable(scratch_url) -> None:
    engine = create_engine(scratch_url)
    try:
        migrate(engine, "0010")
        with engine.begin() as connection:
            _insert_chunk(connection, "Refunds are accepted")

        migrate(engine)
        [(content, english, simple)] = _search_columns(engine)
        assert content == "Refunds are accepted"
        assert english == "'accept':3 'refund':1"
        assert simple == "'accepted':3 'are':2 'refunds':1"

        downgrade(engine, "0010")
        migrate(engine)
        [(content, english, _)] = _search_columns(engine)
        assert content == "Refunds are accepted"
        assert english == "'accept':3 'refund':1"
    finally:
        engine.dispose()


def test_new_chunks_get_search_columns_without_the_application(scratch_url) -> None:
    engine = create_engine(scratch_url)
    try:
        migrate(engine)
        with engine.begin() as connection:
            _insert_chunk(connection, "fees kitni hai")
        [(_, english, simple)] = _search_columns(engine)
        assert simple == "'fees':1 'hai':3 'kitni':2"
        assert "'kitni':2" in english
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
