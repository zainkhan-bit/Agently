"""Races on separate connections: at least one owner always remains, and 20 means 20.

Each test holds the contested lock itself, waits until PostgreSQL reports that both requests
are blocked, and only then lets go. The race therefore always happens.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.models import AuthThrottleEvent, Membership, User, Workspace
from app.modules.workspaces import service
from tests.auth_helpers import register

pytestmark = pytest.mark.db


@pytest.fixture
def factory(auth_app, test_engine):
    """Real sessions, one connection per request, committed for real and cleaned up."""
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def real_get_db():
        session = factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    auth_app.dependency_overrides[get_db] = real_get_db
    yield factory
    with factory() as session:
        for model in (AuthThrottleEvent, Workspace, User):
            session.execute(delete(model))
        session.commit()


@pytest.fixture
def two_owners(factory, make_client):
    """Two clients who both own one workspace."""
    clients, ids = [], []
    for name in ("first", "second"):
        client = make_client()
        ids.append(register(client, email=f"{name}@example.com").json()["id"])
        clients.append(client)
    workspace_id = clients[0].post("/api/workspaces", json={"name": "Shared"}).json()["id"]
    with factory() as session:
        session.add(Membership(user_id=ids[1], workspace_id=workspace_id, role="owner"))
        session.commit()
    return clients, ids, uuid.UUID(workspace_id)


def owners_of(factory, workspace_id) -> int:
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.role == "owner")
        )


def wait_until_blocked(factory, expected: int) -> None:
    """Return once exactly this many requests are waiting for a database lock."""
    deadline = time.monotonic() + 20
    waiting = -1
    while waiting != expected and time.monotonic() < deadline:
        with factory() as observer:
            waiting = observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname ="
                    " current_database() AND wait_event_type = 'Lock'"
                )
            )
        time.sleep(0.02)
    assert waiting == expected, "the requests never contended for the lock"


def race(factory, lock, requests) -> list:
    """Run requests while holding ``lock``; release it once all of them are waiting."""
    with factory() as holder, ThreadPoolExecutor(len(requests)) as pool:
        holder.execute(lock)
        futures = []
        try:
            # One at a time, so that they queue in this order.
            for request in requests:
                futures.append(pool.submit(request))
                wait_until_blocked(factory, len(futures))
        finally:
            holder.rollback()
        return [future.result(timeout=20) for future in futures]


def lock_owner_rows(workspace_id):
    return (
        select(Membership)
        .where(Membership.workspace_id == workspace_id, Membership.role == "owner")
        .order_by(Membership.id)
        .with_for_update()
    )


def lock_user_row(user_id):
    return select(User).where(User.id == user_id).with_for_update(key_share=True)


ACTIONS = {
    "demote": lambda client, url, other: client.patch(
        f"{url}/members/{other}", json={"role": "member"}
    ),
    "remove": lambda client, url, other: client.delete(f"{url}/members/{other}"),
    "leave": lambda client, url, other: client.post(f"{url}/leave"),
}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("demote", "demote"),
        ("remove", "remove"),
        ("demote", "remove"),
        ("leave", "leave"),
        ("leave", "demote"),
        ("leave", "remove"),
    ],
)
def test_one_owner_always_remains(factory, two_owners, first, second) -> None:
    """Each owner acts against the other (or leaves) at the same moment."""
    clients, ids, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}"
    responses = race(
        factory,
        lock_owner_rows(workspace_id),
        [
            lambda: ACTIONS[first](clients[0], url, ids[1]),
            lambda: ACTIONS[second](clients[1], url, ids[0]),
        ],
    )
    codes = sorted(response.status_code for response in responses)
    assert codes[0] in (200, 204)
    assert codes[1] in (403, 404, 409)
    assert owners_of(factory, workspace_id) == 1


def test_owner_demoted_while_waiting_cannot_delete_or_rename(factory, two_owners) -> None:
    """Both requests passed the early owner check and are waiting when the demotion commits."""
    clients, ids, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}"
    with factory() as demoter, ThreadPoolExecutor(2) as pool:
        try:
            demoter.execute(lock_owner_rows(workspace_id))
            futures = [
                pool.submit(lambda: clients[1].delete(url)),
                pool.submit(lambda: clients[1].patch(url, json={"name": "Renamed"})),
            ]
            wait_until_blocked(factory, 2)
            demoter.execute(
                update(Membership)
                .where(Membership.workspace_id == workspace_id, Membership.user_id == ids[1])
                .values(role="member")
            )
            demoter.commit()
        finally:
            demoter.rollback()
        assert [future.result(timeout=20).status_code for future in futures] == [403, 403]
    assert clients[0].get(url).json()["name"] == "Shared"


def test_member_changes_lock_the_workspace_and_its_owner_rows(factory, two_owners) -> None:
    _, ids, workspace_id = two_owners
    with factory() as holder, factory() as observer:
        workspace = holder.get(Workspace, workspace_id)
        context = service.WorkspaceContext(workspace, uuid.UUID(ids[0]), "owner")
        assert len(service._lock_owners(holder, context)) == 2
        free_owners = observer.scalars(
            lock_owner_rows(workspace_id).with_for_update(skip_locked=True)
        ).all()
        free_workspaces = observer.scalars(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .with_for_update(key_share=True, skip_locked=True)
        ).all()
        assert (free_owners, free_workspaces) == ([], [])
        observer.rollback()


def test_someone_promoted_while_a_request_waits_is_seen(factory, two_owners) -> None:
    """The old owner can leave behind a promotion instead of getting a false refusal."""
    clients, ids, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}"
    with factory() as session:  # the first owner becomes the only one
        session.execute(
            update(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.user_id == ids[1])
            .values(role="member")
        )
        session.commit()
    responses = race(
        factory,
        lock_owner_rows(workspace_id),
        [
            lambda: clients[0].patch(f"{url}/members/{ids[1]}", json={"role": "owner"}),
            lambda: ACTIONS["leave"](clients[0], url, ids[1]),
        ],
    )
    assert [r.status_code for r in responses] == [200, 204]
    assert owners_of(factory, workspace_id) == 1


def test_rename_does_not_read_the_workspace_after_releasing_its_lock(factory, two_owners) -> None:
    """A delete waiting on the lock wins the moment the rename commits."""
    _, ids, workspace_id = two_owners

    def delete_it(_session) -> None:
        with factory() as other:
            other.execute(delete(Workspace).where(Workspace.id == workspace_id))
            other.commit()

    with factory() as session:
        workspace = session.get(Workspace, workspace_id)
        context = service.WorkspaceContext(workspace, uuid.UUID(ids[0]), "owner")
        event.listen(session, "after_commit", delete_it)
        assert service.rename_workspace(session, context, "Renamed").name == "Renamed"


def test_parallel_creates_cannot_pass_the_limit(factory, make_client) -> None:
    client = make_client()
    user_id = uuid.UUID(register(client, email="many@example.com").json()["id"])
    with factory() as session:  # 19 owned, counting the personal workspace
        for n in range(18):
            service.add_workspace(session, user_id, f"W{n}")
        session.commit()

    def create():
        return client.post("/api/workspaces", json={"name": "Race"})

    responses = race(factory, lock_user_row(user_id), [create, create, create])
    assert sorted(response.status_code for response in responses) == [201, 409, 409]
    assert len(client.get("/api/workspaces").json()) == 20


def test_create_and_promotion_cannot_pass_the_limit_together(
    factory, two_owners, make_client, monkeypatch
) -> None:
    clients, _, workspace_id = two_owners
    target = make_client()
    target_id = uuid.UUID(register(target, email="target@example.com").json()["id"])
    with factory() as session:
        session.add(Membership(user_id=target_id, workspace_id=workspace_id, role="member"))
        session.commit()
    monkeypatch.setattr(service, "MAX_OWNED_WORKSPACES", 2)
    responses = race(
        factory,
        lock_user_row(target_id),
        [
            lambda: target.post("/api/workspaces", json={"name": "Mine"}),
            lambda: clients[0].patch(
                f"/api/workspaces/{workspace_id}/members/{target_id}", json={"role": "owner"}
            ),
        ],
    )
    assert [r.status_code for r in responses] in ([201, 409], [409, 200])


def test_delete_queued_behind_a_demotion_is_refused(factory, two_owners) -> None:
    clients, ids, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}"
    responses = race(
        factory,
        lock_owner_rows(workspace_id),
        [
            lambda: ACTIONS["demote"](clients[1], url, ids[0]),
            lambda: clients[0].delete(url),
        ],
    )
    assert [r.status_code for r in responses] == [200, 403]


def test_demotion_queued_behind_a_delete_finds_nothing(factory, two_owners) -> None:
    clients, ids, workspace_id = two_owners
    url = f"/api/workspaces/{workspace_id}"
    responses = race(
        factory,
        lock_owner_rows(workspace_id),
        [
            lambda: clients[0].delete(url),
            lambda: ACTIONS["demote"](clients[1], url, ids[0]),
        ],
    )
    assert [r.status_code for r in responses] == [204, 404]


def test_signing_in_is_not_blocked_by_the_limit_lock(factory, make_client) -> None:
    from tests.auth_helpers import login

    client = make_client()
    user_id = uuid.UUID(register(client, email="busy@example.com").json()["id"])
    with factory() as holder, ThreadPoolExecutor(1) as pool:
        service.add_workspace(holder, user_id, "Uncommitted")
        future = pool.submit(lambda: login(make_client(), email="busy@example.com").status_code)
        try:
            assert future.result(timeout=10) == 200
        finally:
            holder.rollback()
