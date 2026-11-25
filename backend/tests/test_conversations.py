"""Conversations: operations, limits, storing, deletion and races. Isolation: the matrix."""

# The imported fixtures are used as arguments.
# ruff: noqa: F401, F811

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import NotFoundError
from app.models import Agent, Conversation, Membership, ProviderSpend, StoredMessage, Workspace
from app.modules.conversations import service
from app.modules.conversations.service import MessageInvalidError, MessageLimitError
from app.modules.workspaces.service import WorkspaceContext
from tests.test_agent_concurrency import lock_workspace, shared
from tests.test_agents_api import code, count, create, s
from tests.test_workspace_concurrency import factory, race, two_owners, wait_until_blocked

pytestmark = pytest.mark.db


@pytest.fixture
def c(s):
    """An agent with one conversation of its member."""
    s.agent = uuid.UUID(create(s.owner, s.url)["id"])
    s.agent_url = f"{s.url}/{s.agent}"
    s.chats = f"{s.agent_url}/conversations"
    s.chat = start(s.member, s.chats)
    s.chat_id = uuid.UUID(s.chat["id"])
    s.one = f"{s.chats}/{s.chat_id}"
    return s


def start(client, url) -> dict:
    response = client.post(url)
    assert response.status_code == 201, response.text
    return response.json()


def context(session, workspace, user_id, role="member") -> WorkspaceContext:
    found = session.get(Workspace, uuid.UUID(str(workspace)))
    return WorkspaceContext(workspace=found, user_id=uuid.UUID(user_id), role=role)


def store(session, c, role="user", content="Hello", version=None, **ids):
    stored = service.store_message(
        session,
        context(session, c.workspace, ids.get("user_id", c.member_id)),
        ids.get("agent_id", c.agent),
        ids.get("conversation_id", c.chat_id),
        role=role,
        content=content,
        agent_version=version,
    )
    session.commit()
    return stored


def messages(client, one, **query) -> dict:
    response = client.get(f"{one}/messages", params=query)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_member_starts_lists_reads_and_deletes_a_conversation(c, db_session) -> None:
    assert set(c.chat) == {"id", "agent_id", "message_count", "created_at", "updated_at"}
    assert (c.chat["agent_id"], c.chat["message_count"]) == (str(c.agent), 0)
    assert c.member.get(c.one).json() == c.chat
    store(db_session, c)
    store(db_session, c, "assistant", "Hi there", 1)
    page = messages(c.member, c.one)
    assert [
        (m["sequence"], m["role"], m["content"], m["agent_version"]) for m in page["items"]
    ] == [
        (1, "user", "Hello", None),
        (2, "assistant", "Hi there", 1),
    ]
    assert set(page["items"][0]) == {
        "id", "sequence", "role", "content", "agent_version", "request_id", "created_at",
    }  # fmt: skip
    assert page["next_before"] is None
    listed = c.member.get(c.chats).json()
    assert listed["total"] == 1 and listed["items"][0]["message_count"] == 2
    assert "Hello" not in str(listed)
    for url in (c.chats, c.one, f"{c.one}/messages"):
        assert c.member.get(url).headers["Cache-Control"] == "private, no-store"
    assert c.member.delete(c.one).status_code == 204
    for response in (
        c.member.get(c.one),
        c.member.delete(c.one),
        c.member.get(f"{c.one}/messages"),
    ):
        assert response.status_code == 404
    assert count(db_session, StoredMessage) == count(db_session, Conversation) == 0


@pytest.mark.parametrize("verb", ["POST", "PUT", "PATCH", "DELETE"])
def test_no_route_accepts_an_assistants_words(c, db_session, verb) -> None:
    body = {"role": "assistant", "content": "forged", "agent_version": 1}
    body |= {"request_id": str(uuid.uuid4())}
    refused = 422 if verb == "POST" else 405
    assert c.member.request(verb, f"{c.one}/messages", json=body).status_code == refused
    assert c.member.post(c.chats, json={"messages": [body]}).status_code == 201
    assert count(db_session, StoredMessage) == 0


def test_the_list_is_paged_with_the_newest_activity_first(c, db_session, advance) -> None:
    ids = [c.chat["id"]]
    for minute in (1, 2):
        advance(minutes=minute)
        ids.append(start(c.member, c.chats)["id"])
    advance(minutes=3)
    store(db_session, c)
    order = [ids[0], ids[2], ids[1]]
    assert [i["id"] for i in c.member.get(c.chats).json()["items"]] == order
    second = c.member.get(c.chats, params={"limit": 1, "offset": 1}).json()
    assert ([i["id"] for i in second["items"]], second["total"]) == ([order[1]], 3)
    assert c.member.get(c.chats, params={"limit": 101}).status_code == 422


def test_history_is_paged_backwards_and_each_page_is_in_order(c, db_session) -> None:
    for number in range(1, 2 * service.MESSAGE_PAGE + 2):
        store(db_session, c, content=f"m{number}")
    seen, before, sizes = [], None, []
    while True:
        page = messages(c.member, c.one, **({"before": before} if before else {}))
        sizes.append(len(page["items"]))
        seen = [m["sequence"] for m in page["items"]] + seen
        before = page["next_before"]
        if before is None:
            break
    assert sizes == [50, 50, 1]
    assert seen == list(range(1, 102))
    assert c.member.get(f"{c.one}/messages", params={"before": 0}).status_code == 422


def test_a_full_last_page_has_no_next(c, db_session) -> None:
    for _ in range(service.MESSAGE_PAGE):
        store(db_session, c)
    assert messages(c.member, c.one)["next_before"] is None


@pytest.mark.parametrize("content", ["", "  \n\t", "​", "a\x00b", "a\ud800b", "x" * 8_001])
def test_invalid_user_text_is_refused(c, db_session, content) -> None:
    with pytest.raises(MessageInvalidError):
        store(db_session, c, content=content)
    assert count(db_session, StoredMessage) == 0


def test_length_limits_differ_by_role(c, db_session, configure) -> None:
    assert len(store(db_session, c, content="x" * 8_000).content) == 8_000
    assert len(store(db_session, c, "assistant", "x" * 32_000, 1).content) == 32_000
    with pytest.raises(MessageInvalidError):
        store(db_session, c, "assistant", "x" * 32_001, 1)
    configure(user_message_max_characters=3, assistant_message_max_characters=4)
    with pytest.raises(MessageInvalidError):
        store(db_session, c, content="xxxx")
    store(db_session, c, "assistant", "xxxx", 1)


@pytest.mark.parametrize(
    ("role", "version"),
    [("system", None), ("", None), ("assistant", None), ("user", 1), ("User", None)],
)
def test_invalid_roles_and_versions_are_refused(c, db_session, role, version) -> None:
    with pytest.raises(ValueError, match="role"):
        store(db_session, c, role, "Hello", version)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"role": "system"}, "ck_messages_role_valid"),
        ({"role": "assistant"}, "ck_messages_version_of_assistant"),
        ({"agent_version": 1}, "ck_messages_version_of_assistant"),
        ({"role": "assistant", "agent_version": 2}, "fk_messages_agent_id_agent_versions"),
        ({"content": ""}, "ck_messages_content_not_empty"),
        ({"sequence": 0}, "ck_messages_sequence_positive"),
        ({"sequence": 1}, "uq_messages_conversation_id_sequence"),
        ({"agent_id": uuid.uuid4()}, "fk_messages_conversation_id_conversations"),
    ],
)
def test_the_database_refuses_inconsistent_messages(c, db_session, values, constraint) -> None:
    store(db_session, c)
    base = {"conversation_id": c.chat_id, "agent_id": c.agent, "sequence": 2}
    db_session.add(StoredMessage(**base | {"role": "user", "content": "x"} | values))
    with pytest.raises(IntegrityError, match=constraint):
        db_session.flush()


def test_a_version_of_another_agent_is_refused(c, db_session) -> None:
    """Version 2 exists, but only of the sibling."""
    other = f"{c.url}/{create(c.owner, c.url)['id']}"
    c.owner.patch(other, json={"version": 1, "name": "N"})
    with pytest.raises(IntegrityError, match="fk_messages_agent_id_agent_versions"):
        store(db_session, c, "assistant", "Hi", 2)


def test_the_database_refuses_a_foreign_agent_or_person(c, db_session) -> None:
    other = uuid.UUID(c.outsider.get("/api/workspaces").json()[0]["id"])
    mine = {
        "workspace_id": uuid.UUID(c.workspace),
        "agent_id": c.agent,
        "user_id": uuid.UUID(c.member_id),
    }
    outsider = db_session.scalar(select(Membership.user_id).where(Membership.workspace_id == other))
    for values in ({"workspace_id": other, "user_id": outsider}, {"user_id": outsider}):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(Conversation(**mine | values))
            db_session.flush()


def test_the_answers_version_stays_after_the_agent_changes(c, db_session) -> None:
    store(db_session, c, "assistant", "Old answer", 1)
    c.owner.patch(c.agent_url, json={"version": 1, "instructions": "New."})
    store(db_session, c, "assistant", "New answer", 2)
    assert [m["agent_version"] for m in messages(c.member, c.one)["items"]] == [1, 2]


def test_storing_needs_the_creator_the_agent_and_the_membership(c, db_session) -> None:
    other_agent = uuid.UUID(create(c.owner, c.url)["id"])
    for ids in (
        {"user_id": c.owner_id},
        {"agent_id": other_agent},
        {"conversation_id": uuid.uuid4()},
    ):
        with pytest.raises(NotFoundError):
            store(db_session, c, **ids)
        db_session.rollback()
    assert count(db_session, StoredMessage) == 0


def test_a_full_conversation_takes_no_more(c, db_session, configure) -> None:
    configure(message_limit_per_conversation=2)
    store(db_session, c)
    store(db_session, c)
    with pytest.raises(MessageLimitError):
        store(db_session, c)
    db_session.rollback()
    assert messages(c.member, c.one)["items"][-1]["sequence"] == 2


def test_the_conversation_cap_counts_each_person_and_agent_alone(c, configure) -> None:
    configure(conversation_limit_per_agent=2)
    start(c.member, c.chats)
    refused = c.member.post(c.chats)
    assert (refused.status_code, code(refused)) == (409, "conversation_limit")
    start(c.owner, c.chats)
    start(c.member, f"{c.url}/{create(c.owner, c.url)['id']}/conversations")
    c.member.delete(c.one)
    start(c.member, c.chats)


def test_the_hourly_creation_limit_is_per_person_across_agents(c, configure, advance) -> None:
    configure(conversation_create_limit=2)  # one was already counted
    start(c.member, f"{c.url}/{create(c.owner, c.url)['id']}/conversations")
    refused = c.member.post(c.chats)
    assert (refused.status_code, code(refused)) == (429, "rate_limited")
    start(c.owner, c.chats)
    advance(minutes=61)
    start(c.member, c.chats)


def test_outsiders_are_not_counted_and_learn_nothing(c, configure) -> None:
    configure(conversation_create_limit=1)
    for _ in range(3):
        assert c.outsider.post(c.chats).status_code == 404


@pytest.mark.parametrize(
    ("action", "error"), [("pause", "agent_paused"), ("archive", "agent_archived")]
)
def test_stopped_agents_keep_their_conversations_but_start_none(
    c, db_session, action, error
) -> None:
    store(db_session, c)
    assert c.owner.post(f"{c.agent_url}/{action}").status_code == 200
    refused = c.member.post(c.chats)
    assert (refused.status_code, code(refused)) == (409, error)
    assert c.member.get(c.chats).json()["total"] == 1
    assert len(messages(c.member, c.one)["items"]) == 1
    assert c.member.delete(c.one).status_code == 204


def test_duplicating_an_agent_copies_no_conversations(c, db_session) -> None:
    copy = c.member.post(f"{c.agent_url}/duplicate").json()["id"]
    assert c.member.get(f"{c.url}/{copy}/conversations").json() == {"items": [], "total": 0}


def test_deleting_one_conversation_leaves_the_others(c, db_session) -> None:
    other = uuid.UUID(start(c.member, c.chats)["id"])
    store(db_session, c)
    store(db_session, c, conversation_id=other, content="keep")
    c.member.delete(c.one)
    assert [m["content"] for m in messages(c.member, f"{c.chats}/{other}")["items"]] == ["keep"]


@pytest.mark.parametrize("what", ["agent", "workspace"])
def test_deleting_the_agent_or_workspace_deletes_everyones_conversations(
    c, db_session, what
) -> None:
    c.owner.patch(c.agent_url, json={"version": 1, "name": "N"})
    owners = uuid.UUID(start(c.owner, c.chats)["id"])
    for version in (1, 2):
        store(db_session, c, "assistant", "Hi", version)
    store(db_session, c, conversation_id=owners, user_id=c.owner_id)
    db_session.add(ProviderSpend(model="m", cost_nano_usd=1, created_at=func.now()))
    db_session.commit()
    c.owner.post("/api/workspaces", json={"name": "Other"})
    target = c.agent_url if what == "agent" else f"/api/workspaces/{c.workspace}"
    assert c.owner.delete(target).status_code == 204
    assert count(db_session, Conversation) == count(db_session, StoredMessage) == 0
    assert count(db_session, ProviderSpend) == 1  # usage survives (ADR-0005)


@pytest.mark.parametrize("how", ["removed", "left", "account"])
def test_going_deletes_only_that_persons_conversations_here(c, db_session, how) -> None:
    store(db_session, c)
    kept = start(c.owner, c.chats)["id"]
    home = c.member.get("/api/workspaces").json()
    elsewhere = next(w["id"] for w in home if w["id"] != c.workspace)
    other_url = f"/api/workspaces/{elsewhere}/agents"
    other_chats = f"{other_url}/{create(c.member, other_url)['id']}/conversations"
    start(c.member, other_chats)
    workspace = f"/api/workspaces/{c.workspace}"
    if how == "removed":
        assert c.owner.delete(f"{workspace}/members/{c.member_id}").status_code == 204
    elif how == "left":
        assert c.member.post(f"{workspace}/leave").status_code == 204
    else:
        db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": c.member_id})
        db_session.commit()
    remaining = {str(i) for i in db_session.scalars(select(Conversation.id))}
    if how == "account":
        assert remaining == {kept}
        return
    assert c.member.get(c.one).status_code == 404
    assert len(remaining) == 2 and kept in remaining
    assert count(db_session, StoredMessage) == 0
    db_session.add(
        Membership(
            user_id=uuid.UUID(c.member_id), workspace_id=uuid.UUID(c.workspace), role="member"
        )
    )
    db_session.commit()
    assert c.member.get(c.chats).json() == {"items": [], "total": 0}
    assert c.member.get(other_chats).json()["total"] == 1


# Races, on separate connections.


@pytest.fixture
def racing(shared, factory):
    clients, ids, workspace_id, url, agent = shared
    chats = f"{url}/{agent}/conversations"
    chat = start(clients[0], chats)["id"]

    def add(content="Hello"):
        with factory() as session:
            mine = context(session, workspace_id, ids[0], "owner")
            session.get(Conversation, uuid.UUID(chat))  # as a request does, before it waits
            try:
                stored = service.store_message(
                    session, mine, uuid.UUID(agent), uuid.UUID(chat), role="user", content=content
                )
                session.commit()
                return stored.sequence
            except NotFoundError:
                return "not found"
            except MessageLimitError:
                return "full"

    return clients, ids, workspace_id, f"{url}/{agent}", f"{chats}/{chat}", add


def test_simultaneous_messages_get_consecutive_numbers(factory, racing) -> None:
    *_, workspace_id, _, _, add = racing
    assert race(factory, lock_workspace(workspace_id), [add, add, add]) == [1, 2, 3]


def test_a_writer_continues_from_a_change_it_waited_for(factory, racing) -> None:
    """The holder has only the conversation, so the workspace lock cannot help."""
    *_, add = racing
    with factory() as holder, ThreadPoolExecutor(1) as pool:
        try:
            holder.execute(update(Conversation).values(message_count=7))
            future = pool.submit(add)
            wait_until_blocked(factory, 1)
            holder.commit()
        finally:
            holder.rollback()
        assert future.result(timeout=20) == 8


def test_simultaneous_messages_cannot_pass_the_limit(factory, racing, configure) -> None:
    *_, workspace_id, _, _, add = racing
    configure(message_limit_per_conversation=1)
    assert race(factory, lock_workspace(workspace_id), [add, add]) == [1, "full"]


def test_simultaneous_creations_cannot_pass_the_cap(factory, racing, configure) -> None:
    clients, _, workspace_id, agent, *_ = racing
    configure(conversation_limit_per_agent=2)
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [lambda: clients[0].post(f"{agent}/conversations")] * 2,
    )
    assert [r.status_code for r in responses] == [201, 409]


def test_a_creation_queued_behind_a_pause_is_refused(factory, racing) -> None:
    clients, _, workspace_id, agent, *_ = racing
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: clients[1].post(f"{agent}/pause"),
            lambda: clients[0].post(f"{agent}/conversations"),
        ],
    )
    assert [r.status_code for r in responses] == [200, 409]


@pytest.mark.parametrize("store_first", [True, False])
@pytest.mark.parametrize("what", ["conversation", "agent", "workspace", "removal"])
def test_storing_and_deleting_do_not_deadlock(factory, racing, what, store_first) -> None:
    clients, ids, workspace_id, agent, one, add = racing
    workspace = f"/api/workspaces/{workspace_id}"
    deletes = {
        "conversation": lambda: clients[0].delete(one).status_code,
        "agent": lambda: clients[1].delete(agent).status_code,
        "workspace": lambda: clients[1].delete(workspace).status_code,
        "removal": lambda: clients[1].delete(f"{workspace}/members/{ids[0]}").status_code,
    }
    requests = [add, deletes[what]] if store_first else [deletes[what], add]
    results = race(factory, lock_workspace(workspace_id), requests)
    assert results == ([1, 204] if store_first else [204, "not found"])
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(StoredMessage)) == 0


def test_a_person_removed_while_creating_gets_404(factory, racing) -> None:
    clients, ids, workspace_id, agent, *_ = racing
    responses = race(
        factory,
        lock_workspace(workspace_id),
        [
            lambda: clients[1].delete(f"/api/workspaces/{workspace_id}/members/{ids[0]}"),
            lambda: clients[0].post(f"{agent}/conversations"),
        ],
    )
    assert [r.status_code for r in responses] == [204, 404]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
