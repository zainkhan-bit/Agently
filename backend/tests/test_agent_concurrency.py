"""Agent races on separate connections. See test_workspace_concurrency for how they are forced."""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, func, select, update

from app.models import Agent, AgentVersion, Membership, Workspace
from app.modules.agents import service
from app.modules.workspaces.service import WorkspaceContext
from tests.auth_helpers import register
from tests.test_workspace_concurrency import (
    factory,
    race,
    two_owners,
    wait_until_blocked,
)

pytestmark = pytest.mark.db

BODY = {"name": "Helper", "instructions": "Be kind."}


@pytest.fixture
def shared(two_owners):
    clients, ids, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}/agents"
    agent = clients[0].post(url, json=BODY).json()["id"]
    return clients, ids, workspace_id, url, agent


def lock_workspace(workspace_id):
    return select(Workspace.id).where(Workspace.id == workspace_id).with_for_update(key_share=True)


def my_membership(workspace_id, user_id):
    return (Membership.workspace_id == workspace_id, Membership.user_id == user_id)


def edit(client, one, version, name):
    return lambda: client.patch(one, json={"version": version, "name": name})


def roll_back(client, one, version=2):
    """To version 1. Reading its id takes no lock, so it never waits."""
    first = client.get(f"{one}/versions", params={"before": 2}).json()["items"][0]["id"]
    return client.post(f"{one}/versions/{first}/rollback", json={"version": version})


def versions(factory, agent) -> list[int]:
    with factory() as session:
        return list(
            session.scalars(
                select(AgentVersion.number)
                .where(AgentVersion.agent_id == uuid.UUID(agent))
                .order_by(AgentVersion.number)
            )
        )


def test_two_edits_of_one_version_save_exactly_once(factory, shared) -> None:
    clients, _, workspace_id, url, agent = shared
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [edit(clients[n], f"{url}/{agent}", 1, f"N{n}") for n in (0, 1)],
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert versions(factory, agent) == [1, 2]


def test_two_edits_at_the_version_cap_save_exactly_once(
    factory,
    shared,
    monkeypatch,
) -> None:
    clients, _, workspace_id, url, agent = shared
    monkeypatch.setattr(service, "MAX_VERSIONS", 2)
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [edit(clients[0], f"{url}/{agent}", version, f"N{version}") for version in (1, 2)],
    )
    # The second edit states the version that the first is about to save.
    assert [r.status_code for r in responses] == [200, 409]
    assert responses[1].json()["error"]["code"] == "version_limit"
    assert versions(factory, agent) == [1, 2]


def test_parallel_create_and_duplicate_cannot_pass_the_cap(
    factory,
    shared,
    configure,
) -> None:
    clients, _, workspace_id, url, agent = shared
    for _ in range(48):
        assert clients[0].post(url, json=BODY).status_code == 201
    clients[0].post(f"{url}/{agent}/archive")
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: clients[0].post(url, json=BODY),
            lambda: clients[1].post(f"{url}/{agent}/duplicate"),
            lambda: clients[1].post(url, json=BODY),
        ],
    )
    assert sorted(r.status_code for r in responses) == [201, 409, 409]
    with factory() as session:
        where = Agent.workspace_id == workspace_id
        assert session.scalar(select(func.count()).select_from(Agent).where(where)) == 50


WRITES = {
    "create": lambda client, url, agent: client.post(url, json=BODY),
    "edit": lambda client, url, agent: client.patch(
        f"{url}/{agent}", json={"version": 1, "name": "N"}
    ),
    "duplicate": lambda client, url, agent: client.post(f"{url}/{agent}/duplicate"),
    "pause": lambda client, url, agent: client.post(f"{url}/{agent}/pause"),
    "archive": lambda client, url, agent: client.post(f"{url}/{agent}/archive"),
    "resume": lambda client, url, agent: client.post(f"{url}/{agent}/resume"),
    "restore": lambda client, url, agent: client.post(f"{url}/{agent}/restore"),
    "rollback": lambda client, url, agent: roll_back(client, f"{url}/{agent}"),
    "delete": lambda client, url, agent: client.delete(f"{url}/{agent}"),
}


def prepare(client, url, agent, write) -> None:
    """Put the agent in the status the write needs."""
    needs = {"resume": "pause", "restore": "archive"}
    if write == "rollback":
        assert edit(client, f"{url}/{agent}", 1, "Second")().status_code == 200
    if write in needs:
        assert client.post(f"{url}/{agent}/{needs[write]}").status_code == 200


@pytest.mark.parametrize("write", WRITES)
def test_member_removed_while_a_write_waits_gets_404(factory, shared, write) -> None:
    clients, ids, workspace_id, url, agent = shared
    prepare(clients[0], url, agent, write)
    before = clients[0].get(f"{url}/{agent}").json()
    with factory() as remover, ThreadPoolExecutor(1) as pool:
        try:
            remover.execute(lock_workspace(workspace_id))
            future = pool.submit(WRITES[write], clients[1], url, agent)
            wait_until_blocked(factory, 1)
            remover.execute(delete(Membership).where(*my_membership(workspace_id, ids[1])))
            remover.commit()
        finally:
            remover.rollback()
        assert future.result(timeout=20).status_code == 404
    assert clients[0].get(f"{url}/{agent}").json() == before
    with factory() as session:
        where = Agent.workspace_id == workspace_id
        assert session.scalar(select(func.count()).select_from(Agent).where(where)) == 1


def test_a_removal_that_holds_only_the_membership_is_also_waited_for(
    factory,
    shared,
) -> None:
    clients, ids, workspace_id, url, agent = shared
    with factory() as remover, ThreadPoolExecutor(1) as pool:
        try:
            remover.execute(delete(Membership).where(*my_membership(workspace_id, ids[1])))
            future = pool.submit(WRITES["edit"], clients[1], url, agent)
            wait_until_blocked(factory, 1)
            remover.commit()
        finally:
            remover.rollback()
        assert future.result(timeout=20).status_code == 404
    assert versions(factory, agent) == [1]


def test_owner_demoted_while_a_delete_waits_is_refused(factory, shared) -> None:
    clients, ids, workspace_id, url, agent = shared
    with factory() as demoter, ThreadPoolExecutor(1) as pool:
        try:
            demoter.execute(lock_workspace(workspace_id))
            future = pool.submit(WRITES["delete"], clients[1], url, agent)
            wait_until_blocked(factory, 1)
            demoter.execute(
                update(Membership).where(*my_membership(workspace_id, ids[1])).values(role="member")
            )
            demoter.commit()
        finally:
            demoter.rollback()
        assert future.result(timeout=20).status_code == 403
    assert clients[0].get(f"{url}/{agent}").status_code == 200


def test_edit_queued_behind_an_archive_is_refused(factory, shared) -> None:
    """The waiting edit must see the new status, not the one it loaded before waiting."""
    clients, _, workspace_id, url, agent = shared
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: WRITES["archive"](clients[0], url, agent),
            lambda: WRITES["edit"](clients[1], url, agent),
        ],
    )
    assert [r.status_code for r in responses] == [200, 409]
    assert responses[1].json()["error"]["code"] == "agent_archived"


@pytest.mark.parametrize("write", list(WRITES)[1:])
def test_write_queued_behind_a_delete_gets_404(factory, shared, write) -> None:
    clients, _, workspace_id, url, agent = shared
    prepare(clients[0], url, agent, write)
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: WRITES["delete"](clients[0], url, agent),
            lambda: WRITES[write](clients[1], url, agent),
        ],
    )
    assert [r.status_code for r in responses] == [204, 404]


@pytest.mark.parametrize("write", WRITES)
@pytest.mark.parametrize("delete_first", [True, False])
def test_workspace_delete_and_a_write_do_not_deadlock(
    factory,
    shared,
    write,
    delete_first,
) -> None:
    clients, _, workspace_id, url, agent = shared
    prepare(clients[0], url, agent, write)
    requests = [
        lambda: clients[0].delete(f"/api/workspaces/{workspace_id}"),
        lambda: WRITES[write](clients[1], url, agent),
    ]
    if not delete_first:
        requests.reverse()
    responses = race(factory, lock_workspace(workspace_id), requests)
    deleted, written = responses if delete_first else reversed(responses)
    assert deleted.status_code == 204
    assert written.status_code == 404 if delete_first else written.status_code in (200, 201, 204)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Agent)) == 0


def test_no_lock_is_held_while_the_throttle_commits(factory, make_client) -> None:
    """A refused write never waits for the workspace lock: the throttle comes first."""
    from app.core.config import get_settings

    client = make_client()
    register(client, email="solo@example.com")
    workspace = client.get("/api/workspaces").json()[0]["id"]
    url = f"/api/workspaces/{workspace}/agents"
    get_settings().agent_write_limit = 1
    assert client.post(url, json=BODY).status_code == 201
    with factory() as holder:
        holder.execute(lock_workspace(uuid.UUID(workspace)))
        # Would hang here if the lock were taken before the throttle.
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(lambda: client.post(url, json=BODY).status_code)
            try:
                assert future.result(timeout=10) == 429
            finally:
                holder.rollback()


def test_an_edit_that_changes_nothing_releases_its_locks(factory, shared) -> None:
    """Over HTTP the session closes only after the response is sent, which a client can delay."""
    _, ids, workspace_id, _, agent = shared
    with factory() as session, factory() as observer:
        context = WorkspaceContext(session.get(Workspace, workspace_id), uuid.UUID(ids[0]), "owner")
        service.update_agent(session, context, uuid.UUID(agent), 1, {"name": "Helper"})
        observer.execute(
            select(Workspace.id)
            .where(Workspace.id == workspace_id)
            .with_for_update(key_share=True, nowait=True)
        )


def test_two_rollbacks_of_one_version_save_exactly_once(factory, shared) -> None:
    clients, _, workspace_id, url, agent = shared
    one = f"{url}/{agent}"
    prepare(clients[0], url, agent, "rollback")
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [lambda: roll_back(clients[0], one), lambda: roll_back(clients[1], one)],
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert versions(factory, agent) == [1, 2, 3]


@pytest.mark.parametrize("rollback_first", [True, False])
def test_a_rollback_and_an_edit_of_one_version_save_exactly_once(
    factory, shared, rollback_first
) -> None:
    clients, _, workspace_id, url, agent = shared
    one = f"{url}/{agent}"
    prepare(clients[0], url, agent, "rollback")
    requests = [lambda: roll_back(clients[0], one), edit(clients[1], one, 2, "Edited")]
    if not rollback_first:
        requests.reverse()
    responses = race(factory, lock_workspace(workspace_id), requests)
    assert [r.status_code for r in responses] == [200, 409]
    assert responses[1].json()["error"]["code"] == "version_conflict"
    assert versions(factory, agent) == [1, 2, 3]


def test_two_rollbacks_at_the_version_cap_save_exactly_once(factory, shared, monkeypatch) -> None:
    clients, _, workspace_id, url, agent = shared
    one = f"{url}/{agent}"
    prepare(clients[0], url, agent, "rollback")
    monkeypatch.setattr(service, "MAX_VERSIONS", 3)
    second = clients[0].get(f"{one}/versions").json()["items"][0]["id"]
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: roll_back(clients[0], one),
            # States the version that the first is about to save.
            lambda: clients[1].post(f"{one}/versions/{second}/rollback", json={"version": 3}),
        ],
    )
    assert [r.status_code for r in responses] == [200, 409]
    assert responses[1].json()["error"]["code"] == "version_limit"
    assert versions(factory, agent) == [1, 2, 3]


def test_rollback_queued_behind_an_archive_is_refused(factory, shared) -> None:
    clients, _, workspace_id, url, agent = shared
    prepare(clients[0], url, agent, "rollback")
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: WRITES["archive"](clients[0], url, agent),
            lambda: WRITES["rollback"](clients[1], url, agent),
        ],
    )
    assert [r.status_code for r in responses] == [200, 409]
    assert responses[1].json()["error"]["code"] == "agent_archived"
    assert versions(factory, agent) == [1, 2]


def test_a_rollback_that_changes_nothing_releases_its_locks(factory, shared) -> None:
    _, ids, workspace_id, _, agent = shared
    with factory() as session, factory() as observer:
        context = WorkspaceContext(session.get(Workspace, workspace_id), uuid.UUID(ids[0]), "owner")
        version = session.scalar(
            select(AgentVersion.id).where(AgentVersion.agent_id == uuid.UUID(agent))
        )
        service.roll_back(session, context, uuid.UUID(agent), version, 1)
        observer.execute(
            select(Workspace.id)
            .where(Workspace.id == workspace_id)
            .with_for_update(key_share=True, nowait=True)
        )
