"""A stuck write cannot block a workspace forever: waiters get 503, idle holders are ended."""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.models import Agent, AgentVersion, Membership, Workspace
from app.modules.agents import service as agents
from tests.auth_helpers import ORIGIN
from tests.test_agent_concurrency import WRITES as AGENT_WRITES
from tests.test_agent_concurrency import lock_workspace, prepare, shared
from tests.test_workspace_concurrency import ACTIONS, factory, lock_user_row, two_owners

pytestmark = pytest.mark.db

WORKSPACE_WRITES = {
    "rename": lambda client, url, other: client.patch(url, json={"name": "N"}),
    "promote": lambda client, url, other: client.patch(
        f"{url}/members/{other}", json={"role": "owner"}
    ),
    "delete workspace": lambda client, url, other: client.delete(url),
    **ACTIONS,
}


def snapshot(factory) -> list:
    with factory() as session:
        return [
            session.execute(select(model.__table__).order_by(model.id)).all()
            for model in (Workspace, Membership, Agent, AgentVersion)
        ]


def assert_busy(response) -> None:
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "busy"
    assert "busy" in error["message"] and "try again" in error["message"]
    assert "Nothing was changed" in error["message"]


def assert_busy_while_locked(factory, lock, request) -> None:
    before = snapshot(factory)
    with factory() as holder, ThreadPoolExecutor(1) as pool:
        holder.execute(lock)
        try:
            response = pool.submit(request).result(timeout=20)
        finally:
            holder.rollback()
    assert_busy(response)
    assert snapshot(factory) == before


@pytest.mark.parametrize("write", AGENT_WRITES)
def test_agent_write_gives_up_waiting(factory, shared, configure, write) -> None:
    clients, _, workspace_id, url, agent = shared
    prepare(clients[0], url, agent, write)
    configure(write_lock_timeout_seconds=1)
    assert_busy_while_locked(
        factory,
        lock_workspace(workspace_id),
        lambda: AGENT_WRITES[write](clients[0], url, agent),
    )
    assert AGENT_WRITES[write](clients[0], url, agent).is_success


@pytest.mark.parametrize("write", WORKSPACE_WRITES)
def test_workspace_write_gives_up_waiting(factory, two_owners, configure, write) -> None:
    clients, ids, workspace_id = two_owners
    configure(write_lock_timeout_seconds=1)
    url = f"/api/workspaces/{workspace_id}"
    assert_busy_while_locked(
        factory,
        lock_workspace(workspace_id),
        lambda: WORKSPACE_WRITES[write](clients[0], url, ids[1]),
    )
    assert WORKSPACE_WRITES[write](clients[0], url, ids[1]).is_success


def test_creating_a_workspace_gives_up_waiting(factory, two_owners, configure) -> None:
    clients, ids, _ = two_owners
    configure(write_lock_timeout_seconds=1)
    assert_busy_while_locked(
        factory,
        lock_user_row(ids[0]),
        lambda: clients[0].post("/api/workspaces", json={"name": "New"}),
    )


def test_an_idle_holder_is_ended_and_the_workspace_recovers(
    factory, shared, configure, monkeypatch
) -> None:
    clients, _, _, url, agent = shared
    configure(write_idle_timeout_seconds=1, write_lock_timeout_seconds=10)
    real = agents._add_version
    stall = [True]

    def stalls_once(*args):
        if stall and stall.pop():
            time.sleep(3)  # holds every lock and sends nothing
        return real(*args)

    monkeypatch.setattr(agents, "_add_version", stalls_once)
    edit = {"version": 1, "name": "Stalled"}
    with ThreadPoolExecutor(1) as pool:
        stalled = pool.submit(clients[0].patch, f"{url}/{agent}", json=edit)
        deadline = time.monotonic() + 10
        while stall and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not stall
        # Waits for the stalled edit's locks until the database ends it.
        saved = clients[1].patch(f"{url}/{agent}", json={"version": 1, "name": "Second"})
        assert not stalled.done(), "the write must succeed while the first is still stalled"
        assert_busy(stalled.result(timeout=20))
    assert saved.status_code == 200
    assert clients[0].get(f"{url}/{agent}").json()["name"] == "Second"


def test_the_limits_end_with_the_transaction(factory, shared, monkeypatch) -> None:
    """Pooled connections are shared with reads, which must not inherit the limits."""
    clients, _, _, url, agent = shared
    seen = []
    real = agents._add_version

    def show(session):
        return [
            session.scalar(text(f"SHOW {name}"))
            for name in ("lock_timeout", "idle_in_transaction_session_timeout")
        ]

    def spy(db, *args):
        seen.append(show(db))
        connections.append(db.connection().connection.dbapi_connection)
        return real(db, *args)

    connections = []
    monkeypatch.setattr(agents, "_add_version", spy)
    edit = {"version": 1, "name": "N"}
    assert clients[0].patch(f"{url}/{agent}", json=edit).status_code == 200
    assert seen == [["5s", "30s"]]
    # The very connection that was used: the pool may hand out another one.
    pooled = connections[0]
    changed = pooled.execute(
        "SELECT name FROM pg_settings WHERE setting <> reset_val"
        " AND name IN ('lock_timeout', 'idle_in_transaction_session_timeout')"
    ).fetchall()
    assert changed == []
    pooled.rollback()


def test_other_database_errors_are_still_500(auth_app, shared, monkeypatch) -> None:
    clients, _, _, url, agent = shared

    def broken(db, *args, **kwargs):
        db.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(agents, "update_agent", broken)
    client = TestClient(
        auth_app,
        base_url="https://testserver",
        raise_server_exceptions=False,
        headers={"Origin": ORIGIN},
        cookies=clients[0].cookies,
    )
    response = client.patch(f"{url}/{agent}", json={"version": 1, "name": "N"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_a_connection_lost_at_commit_never_claims_nothing_changed(
    auth_app, factory, shared, test_engine, monkeypatch
) -> None:
    clients, _, _, url, agent = shared
    real = agents._add_version

    def then_lose_connection(db, *args):
        version = real(db, *args)
        pid = db.scalar(text("SELECT pg_backend_pid()"))
        with factory() as other:
            other.execute(text("SELECT pg_terminate_backend(:pid, 5000)"), {"pid": pid})
        return version

    monkeypatch.setattr(agents, "_add_version", then_lose_connection)
    failed = []

    def record(context):
        failed.append((context.statement, context.is_disconnect))

    # First, because the application's own listener raises.
    event.listen(test_engine, "handle_error", record, insert=True)
    client = TestClient(
        auth_app,
        base_url="https://testserver",
        raise_server_exceptions=False,
        headers={"Origin": ORIGIN},
        cookies=clients[0].cookies,
    )
    response = client.patch(f"{url}/{agent}", json={"version": 1, "name": "N"})
    event.remove(test_engine, "handle_error", record)
    assert failed[0] == (None, True), "it must be the COMMIT that failed"
    assert response.status_code == 500
