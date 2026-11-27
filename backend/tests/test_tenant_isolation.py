"""Tenant isolation matrix: the Phase 1 exit-gate proof.

Generated from the registered routes. Every route must either resolve a workspace through
``get_workspace_context`` or be listed below as belonging to no workspace, whatever its path looks
like, so a new route cannot be missed. Workspace routes are then attacked by another tenant.
"""

import re
import uuid
from urllib.parse import quote

import pytest
from fastapi import Depends
from fastapi.routing import iter_route_contexts
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import create_app
from app.models import AgentVersion, Base, Conversation, Membership
from app.modules.conversations.dependencies import get_conversation
from app.modules.conversations.service import store_message
from app.modules.identity.router import PUBLIC_ROUTES
from app.modules.workspaces.dependencies import get_workspace_context
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.service import WorkspaceContext
from tests.auth_helpers import register

VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
PREFIX = "/api/workspaces"

# Signed-in routes that belong to no workspace. Adding one here is a security decision: the route
# must only ever use the caller's own user id.
NO_WORKSPACE_ROUTES = {
    ("GET", "/api/auth/me"),
    ("GET", PREFIX),
    ("POST", PREFIX),
}


def _depends_on(dependant, call) -> bool:
    return any(child.call is call or _depends_on(child, call) for child in dependant.dependencies)


def _verbs(route) -> set[str]:
    # Mounts and websockets have no methods: they must not slip through as "no verbs".
    return (getattr(route, "methods", None) or {"ANY"}) - {"HEAD", "OPTIONS"}


def _classify(app) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """All (verb, path) pairs that use the membership check, and all that do not."""
    guarded, other = set(), set()
    for route in iter_route_contexts(app.routes):
        dependant = getattr(route, "dependant", None)
        is_guarded = dependant is not None and _depends_on(dependant, get_workspace_context)
        target = guarded if is_guarded else other
        target |= {(verb, getattr(route, "path", "?")) for verb in _verbs(route)}
    return guarded, other


def _parameters(path: str) -> set[str]:
    return set(re.findall(r"\{(\w+)", path))


GUARDED, OTHER = _classify(create_app())
MATRIX = sorted(GUARDED)
CHILD_MATRIX = [(verb, path) for verb, path in MATRIX if _parameters(path) - {"workspace_id"}]
# People can belong to several workspaces. Everything else belongs to exactly one.
OBJECT_MATRIX = [
    (verb, path) for verb, path in MATRIX if _parameters(path) - {"workspace_id", "user_id"}
]


def _child_swaps(matrix) -> list[tuple[str, str, str]]:
    """One parameter at a time, so a check on one cannot hide a missing check on another."""
    return [
        (verb, path, name)
        for verb, path in matrix
        for name in sorted(_parameters(path) - {"workspace_id"})
    ]


CHILD_SWAPS = _child_swaps(CHILD_MATRIX)
OBJECT_SWAPS = [swap for swap in CHILD_SWAPS if swap[2] != "user_id"]


def _nested_swaps(object_swaps) -> list[tuple[str, str, str]]:
    """Routes naming an object inside another one: both must belong together."""
    return [
        (verb, path, name)
        for verb, path, name in object_swaps
        if len(_parameters(path) - {"workspace_id", "user_id"}) > 1
    ]


NESTED_SWAPS = _nested_swaps(OBJECT_SWAPS)
# What all members of a workspace share. Adding one here is a privacy decision: everything else
# is private to one person, so teammates attack it too, whatever their role.
SHARED = {"workspace_id", "user_id", "agent_id", "version_id", "source_id"}
PRIVATE_MATRIX = [(verb, path) for verb, path in MATRIX if _parameters(path) - SHARED]
GET_PATHS = [path for verb, path in MATRIX if verb == "GET"]


def test_every_route_uses_the_membership_check_or_is_allowlisted() -> None:
    assert OTHER == PUBLIC_ROUTES | NO_WORKSPACE_ROUTES


def test_workspace_routes_name_the_workspace_in_the_path() -> None:
    """Not in the body or query string, so the check sees exactly what the route uses."""
    assert [path for _, path in MATRIX if "{workspace_id}" not in path] == []


def test_matrix_covers_the_known_endpoints() -> None:
    """A floor, so that a broken generator cannot pass by finding nothing."""
    one = f"{PREFIX}/{{workspace_id}}"
    member = f"{one}/members/{{user_id}}"
    assert set(MATRIX) >= {
        ("GET", one),
        ("PATCH", one),
        ("DELETE", one),
        ("POST", f"{one}/leave"),
        ("GET", f"{one}/members"),
        ("PATCH", member),
        ("DELETE", member),
    }
    assert set(CHILD_MATRIX) >= {("PATCH", member), ("DELETE", member)}
    agent = f"{one}/agents/{{agent_id}}"
    agent_routes = {(verb, agent) for verb in ("GET", "PATCH", "DELETE")} | {
        ("POST", f"{agent}/{action}")
        for action in ("duplicate", "pause", "resume", "archive", "restore")
    }
    assert set(MATRIX) >= agent_routes | {("GET", f"{one}/agents"), ("POST", f"{one}/agents")}
    assert set(OBJECT_MATRIX) >= agent_routes
    version = f"{agent}/versions/{{version_id}}"
    version_routes = {("GET", version), ("POST", f"{version}/rollback")}
    assert set(MATRIX) >= version_routes | {("GET", f"{agent}/versions")}
    assert set(NESTED_SWAPS) >= {
        (verb, path, name) for verb, path in version_routes for name in ("agent_id", "version_id")
    }
    chats = f"{agent}/conversations"
    chat = f"{chats}/{{conversation_id}}"
    private = {("GET", chat), ("DELETE", chat)}
    private |= {("GET", f"{chat}/messages"), ("POST", f"{chat}/messages")}
    private |= {("POST", f"{chat}/messages/stream"), ("POST", f"{chat}/messages/stop")}
    assert set(MATRIX) >= private | {("GET", chats), ("POST", chats)}
    assert set(PRIVATE_MATRIX) >= private
    assert set(NESTED_SWAPS) >= {
        (verb, path, name) for verb, path in private for name in ("agent_id", "conversation_id")
    }
    sources = f"{agent}/sources"
    source = f"{sources}/{{source_id}}"
    assert set(MATRIX) >= {("GET", sources), ("POST", sources), ("GET", source), ("DELETE", source)}
    assert set(NESTED_SWAPS) >= {
        (verb, source, name) for verb in ("GET", "DELETE") for name in ("agent_id", "source_id")
    }


def _private_but_unchecked(app) -> set[tuple[str, str]]:
    """Routes naming a conversation without the dependency that requires its creator."""
    return {
        (verb, route.path)
        for route in iter_route_contexts(app.routes)
        if getattr(route, "dependant", None) is not None
        and _parameters(route.path) - SHARED
        and not _depends_on(route.dependant, get_conversation)
        for verb in _verbs(route)
    }


def test_every_route_naming_a_conversation_requires_its_creator() -> None:
    assert _private_but_unchecked(create_app()) == set()


def test_a_conversation_is_named_in_the_path_only() -> None:
    """Not in a body or query string, where the creator check and the attacks would miss it."""
    api = create_app().openapi()
    elsewhere = [
        (path, parameter["name"])
        for path, operations in api["paths"].items()
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
        if parameter["in"] != "path" and "conversation" in parameter["name"]
    ]
    assert elsewhere == []
    for name, schema in api["components"]["schemas"].items():
        assert "conversation_id" not in schema.get("properties", {}), name


@pytest.mark.parametrize(
    ("verb", "path"),
    [
        ("GET", f"{PREFIX}/{{workspace_id}}/leaky"),
        ("GET", "/api/agents/{agent_id}"),
        ("GET", "/api/x/{workspace_id:path}"),
        ("GET", "/api/documents"),
        ("POST", "/api/chats"),
        ("DELETE", PREFIX),
    ],
)
def test_an_unguarded_route_is_caught_whatever_its_shape(verb, path) -> None:
    app = create_app()
    app.add_api_route(path, lambda: {}, methods=[verb])
    _, other = _classify(app)
    assert other - PUBLIC_ROUTES - NO_WORKSPACE_ROUTES == {(verb, path)}


def test_unguarded_websockets_and_mounts_are_caught() -> None:
    app = create_app()

    @app.websocket("/api/ws")
    async def socket(websocket) -> None: ...

    app.mount("/api/mounted", create_app())
    _, other = _classify(app)
    assert other - PUBLIC_ROUTES - NO_WORKSPACE_ROUTES == {
        ("ANY", "/api/ws"),
        ("ANY", "/api/mounted"),
    }


@pytest.fixture
def tenants(make_client, db_session):
    """Signed-in user A, and user B with a workspace A has nothing to do with."""

    class Tenants:
        pass

    t = Tenants()
    t.a, t.b = make_client(), make_client()
    t.a_id = register(t.a, email="a@example.com").json()["id"]
    t.a_workspace = t.a.get(PREFIX).json()[0]["id"]
    t.b_id = register(t.b, email="tenant-b@example.com").json()["id"]
    t.b_workspace = t.b.post(PREFIX, json={"name": "B private name"}).json()["id"]
    # Real ids of things in B's workspace, by path parameter. A new parameter must be added here
    # with a real object of B's: an invented id would prove nothing.
    t.b_children = {"user_id": t.b_id, **_agent(t.b, t.b_workspace, "B secret agent")}
    t.a_children = {"user_id": t.a_id, **_agent(t.a, t.a_workspace, "A agent")}
    # Another agent in the same workspace, with things of its own.
    t.b_sibling_children = {"user_id": t.b_id, **_agent(t.b, t.b_workspace, "B sibling")}
    # B's other workspace, with an agent of its own.
    (t.b_other_workspace,) = (w["id"] for w in t.b.get(PREFIX).json() if w["id"] != t.b_workspace)
    t.b_other_children = {
        "user_id": t.b_id,
        **_agent(t.b, t.b_other_workspace, "B other agent"),
    }
    for children, workspace in (
        (t.b_children, t.b_workspace),
        (t.b_sibling_children, t.b_workspace),
        (t.b_other_children, t.b_other_workspace),
    ):
        _say(db_session, workspace, children, "B secret message")
    _say(db_session, t.a_workspace, t.a_children, "A message")
    # B's teammates: an owner and a member, each with a conversation of their own.
    t.teammates = {}
    for role in ("owner", "member"):
        client = make_client()
        user_id = register(client, email=f"{role}-mate@example.com").json()["id"]
        db_session.add(
            Membership(user_id=uuid.UUID(user_id), workspace_id=uuid.UUID(t.b_workspace), role=role)
        )
        db_session.commit()
        own = client.post(f"{_agent_url(t.b_workspace, t.b_children)}/conversations")
        assert own.status_code == 201
        t.teammates[role] = (client, own.json()["id"])
    return t


def _agent_url(workspace_id: str, children: dict) -> str:
    return f"{PREFIX}/{workspace_id}/agents/{children['agent_id']}"


def _say(session, workspace_id: str, children: dict, text_: str) -> None:
    """A message in the conversation, so that reading it would leak something."""
    context = WorkspaceContext(
        workspace=session.get(Workspace, uuid.UUID(workspace_id)),
        user_id=uuid.UUID(children["user_id"]),
        role="owner",
    )
    agent, chat = (uuid.UUID(children[name]) for name in ("agent_id", "conversation_id"))
    store_message(session, context, agent, chat, role="user", content=text_)
    session.commit()


def _agent(client, workspace_id: str, name: str) -> dict[str, str]:
    """An agent with two versions, and its first one, so that rolling back would change it."""
    response = client.post(
        f"{PREFIX}/{workspace_id}/agents",
        json={"name": name, "instructions": f"{name} instructions"},
    )
    assert response.status_code == 201
    url = f"{PREFIX}/{workspace_id}/agents/{response.json()['id']}"
    edited = client.patch(url, json={"version": 1, "instructions": f"{name} edited"})
    assert edited.status_code == 200
    first = client.get(f"{url}/versions").json()["items"][-1]
    assert first["number"] == 1
    chat = client.post(f"{url}/conversations")
    assert chat.status_code == 201
    source = client.post(
        f"{url}/sources",
        content=f"{name} knowledge".encode(),
        headers={"Content-Type": "text/plain", "X-File-Name": quote(f"{name} notes.txt")},
    )
    assert source.status_code == 201, source.text
    return {
        "agent_id": response.json()["id"],
        "version_id": first["id"],
        "conversation_id": chat.json()["id"],
        "source_id": source.json()["id"],
    }


def _fill(path: str, workspace_id, children: dict) -> str:
    values = {"workspace_id": workspace_id, **children}
    return re.sub(r"\{(\w+)[^}]*\}", lambda match: str(values[match[1]]), path)


def _snapshot(session) -> dict:
    """Every row of every table, except throttle events."""
    return {
        table.name: session.scalars(text(f"SELECT t::text FROM {table.name} t ORDER BY 1")).all()  # noqa: S608
        for table in Base.metadata.sorted_tables
        if table.name != "auth_throttle_events"
    }


BODY = {"name": "Taken over", "role": "owner"}
# One of these is valid for every write, so that only the access check can refuse it.
VALID_BODIES = (
    BODY,
    {"name": "Moved", "instructions": "x", "version": 2},
    {"version": 2},
    {"request_id": str(uuid.uuid4()), "content": "Hello"},
    {"request_id": str(uuid.uuid4())},  # stopping an answer
)


def _error(response) -> dict:
    return {k: v for k, v in response.json()["error"].items() if k != "request_id"}


def _assert_no_tenant_data(tenants, response) -> None:
    for secret in (
        "tenant-b",
        "B private name",
        "B secret agent",
        tenants.b_id,
        tenants.b_workspace,
        tenants.b_children["agent_id"],
        tenants.b_children["version_id"],
        tenants.b_children["conversation_id"],
        tenants.b_children["source_id"],
        "B secret message",
    ):
        assert secret not in response.text


@pytest.mark.db
@pytest.mark.parametrize("child", ["own", "theirs"])
@pytest.mark.parametrize(("verb", "path"), MATRIX)
def test_outsider_gets_404_and_no_data(tenants, db_session, verb, path, child) -> None:
    """User A, signed in, targets user B's workspace."""
    children = tenants.b_children if child == "theirs" else tenants.a_children
    before = _snapshot(db_session)
    response = tenants.a.request(verb, _fill(path, tenants.b_workspace, children), json=BODY)
    assert response.status_code == 404
    _assert_no_tenant_data(tenants, response)
    # Indistinguishable from a workspace that does not exist.
    missing = tenants.a.request(verb, _fill(path, uuid.uuid4(), children), json=BODY)
    assert missing.status_code == 404
    assert _error(missing) == _error(response)
    assert _snapshot(db_session) == before


@pytest.mark.db
@pytest.mark.parametrize(("verb", "path", "name"), CHILD_SWAPS)
def test_own_workspace_does_not_open_another_tenants_objects(
    tenants, db_session, verb, path, name
) -> None:
    """User A, an owner, uses their own workspace id with the id of something of B's."""
    before = _snapshot(db_session)
    children = tenants.a_children | {name: tenants.b_children[name]}
    response = tenants.a.request(verb, _fill(path, tenants.a_workspace, children), json=BODY)
    assert response.status_code == 404
    _assert_no_tenant_data(tenants, response)
    assert _snapshot(db_session) == before


@pytest.mark.db
@pytest.mark.parametrize(("verb", "path"), MATRIX)
def test_the_rightful_owner_reaches_the_same_objects(tenants, verb, path) -> None:
    """Positive control: the attacks above get 404 for isolation, not for a bad id.

    Access is resolved before the body is validated, so even a 422 proves it was found.
    """
    url = _fill(path, tenants.b_workspace, tenants.b_children)
    status = tenants.b.request(verb, url, json=BODY).status_code
    assert status < 500 and status not in (401, 404, 405)


@pytest.mark.db
@pytest.mark.parametrize("to_other", [True, False])
@pytest.mark.parametrize(("verb", "path", "name"), OBJECT_SWAPS)
def test_one_workspace_does_not_open_the_callers_other_workspace(
    tenants, db_session, verb, path, name, to_other
) -> None:
    """User B owns both workspaces, so only the workspace in the path can refuse this."""
    before = _snapshot(db_session)
    workspace, own, foreign = tenants.b_workspace, tenants.b_children, tenants.b_other_children
    if not to_other:
        workspace, own, foreign = tenants.b_other_workspace, foreign, own
    url = _fill(path, workspace, own | {name: foreign[name]})
    for body in VALID_BODIES:
        assert tenants.b.request(verb, url, json=body).status_code == 404
    assert _snapshot(db_session) == before


@pytest.mark.db
@pytest.mark.parametrize("to_sibling", [True, False])
@pytest.mark.parametrize(("verb", "path", "name"), NESTED_SWAPS)
def test_one_object_does_not_open_what_belongs_to_its_sibling(
    tenants, db_session, verb, path, name, to_sibling
) -> None:
    """Same owner, same workspace, two agents: only the pair of ids in the path can refuse this."""
    before = _snapshot(db_session)
    own, foreign = tenants.b_children, tenants.b_sibling_children
    if not to_sibling:
        own, foreign = foreign, own
    url = _fill(path, tenants.b_workspace, own | {name: foreign[name]})
    missing = _fill(path, tenants.b_workspace, own | {name: uuid.uuid4()})
    for body in VALID_BODIES:
        response = tenants.b.request(verb, url, json=body)
        assert response.status_code == 404
        assert _error(tenants.b.request(verb, missing, json=body)) == _error(response)
        assert "B s" not in response.text
    assert _snapshot(db_session) == before


@pytest.mark.db
@pytest.mark.parametrize(("verb", "path"), sorted({swap[:2] for swap in NESTED_SWAPS}))
def test_the_same_nested_requests_work_with_matching_ids(tenants, verb, path) -> None:
    """Positive control for the attacks above, with the same bodies."""
    for children in (tenants.b_children, tenants.b_sibling_children):
        url = _fill(path, tenants.b_workspace, children)
        statuses = [tenants.b.request(verb, url, json=b).status_code for b in VALID_BODIES]
        assert any(200 <= status < 300 for status in statuses)


@pytest.mark.db
@pytest.mark.parametrize("path", [path for path in GET_PATHS if "{agent_id}" in path])
def test_reading_one_agent_shows_nothing_of_its_sibling(tenants, path) -> None:
    for own, sibling, name in (
        (tenants.b_children, tenants.b_sibling_children, "B sibling"),
        (tenants.b_sibling_children, tenants.b_children, "B secret agent"),
    ):
        response = tenants.b.get(_fill(path, tenants.b_workspace, own))
        assert response.status_code == 200
        for other in (
            name,
            sibling["agent_id"],
            sibling["version_id"],
            sibling["conversation_id"],
            sibling["source_id"],
        ):
            assert other not in response.text


@pytest.mark.db
def test_a_new_version_route_without_the_agent_check_is_caught(tenants, auth_app) -> None:
    """Planted: it checks membership but looks the version up by its id alone."""

    def planted(
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        db: Session = Depends(get_db),  # noqa: B008
        _: object = Depends(get_workspace_context),  # noqa: B008
    ) -> str:
        return db.get(AgentVersion, version_id).name

    path = f"{PREFIX}/{{workspace_id}}/agents/{{agent_id}}/versions/{{version_id}}/new"
    auth_app.add_api_route(path, planted, methods=["GET"])
    guarded, _ = _classify(auth_app)
    swaps = _nested_swaps(_child_swaps(sorted(guarded)))
    assert set(swaps) - set(NESTED_SWAPS) == {
        ("GET", path, "agent_id"),
        ("GET", path, "version_id"),
    }
    foreign = tenants.b_children | {"version_id": tenants.b_sibling_children["version_id"]}
    response = tenants.b.get(_fill(path, tenants.b_workspace, foreign))
    assert (response.status_code, response.json()) == (200, "B sibling")  # the attack would fail


@pytest.mark.db
@pytest.mark.parametrize("role", ["owner", "member"])
@pytest.mark.parametrize(("verb", "path"), PRIVATE_MATRIX)
def test_teammates_cannot_tell_that_a_conversation_exists(
    tenants, db_session, verb, path, role
) -> None:
    """Same workspace, same agent, any role: only the creator check can refuse this."""
    client, own = tenants.teammates[role]
    before = _snapshot(db_session)
    url = _fill(path, tenants.b_workspace, tenants.b_children)
    missing = _fill(
        path, tenants.b_workspace, tenants.b_children | {"conversation_id": uuid.uuid4()}
    )
    for body in VALID_BODIES:
        response = client.request(verb, url, json=body)
        assert response.status_code == 404
        assert _error(response) == _error(client.request(verb, missing, json=body))
        assert "B secret message" not in response.text
    assert _snapshot(db_session) == before
    # Positive control: the same request for their own conversation works.
    mine = _fill(path, tenants.b_workspace, tenants.b_children | {"conversation_id": own})
    statuses = [client.request(verb, mine, json=body).status_code for body in VALID_BODIES]
    assert any(200 <= status < 300 for status in statuses)


@pytest.mark.db
@pytest.mark.parametrize("role", ["owner", "member"])
@pytest.mark.parametrize("path", GET_PATHS)
def test_nothing_a_teammate_reads_shows_a_private_conversation(tenants, path, role) -> None:
    client, own = tenants.teammates[role]
    children = tenants.b_children | {"conversation_id": own}
    response = client.get(_fill(path, tenants.b_workspace, children))
    assert response.status_code == 200
    for private in (tenants.b_children["conversation_id"], "B secret message"):
        assert private not in response.text


@pytest.mark.db
@pytest.mark.parametrize("role", ["owner", "member"])
def test_a_teammates_list_has_only_their_own_conversations(tenants, role) -> None:
    client, own = tenants.teammates[role]
    page = client.get(f"{_agent_url(tenants.b_workspace, tenants.b_children)}/conversations").json()
    assert ([item["id"] for item in page["items"]], page["total"]) == ([own], 1)


@pytest.mark.db
def test_a_new_conversation_route_without_the_creator_check_is_caught(tenants, auth_app) -> None:
    """Planted: it checks membership and agent, but not who the conversation belongs to."""

    def planted(
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        db: Session = Depends(get_db),  # noqa: B008
        _: object = Depends(get_workspace_context),  # noqa: B008
    ) -> int:
        chat = db.get(Conversation, conversation_id)
        return chat.message_count if chat and chat.agent_id == agent_id else -1

    path = f"{PREFIX}/{{workspace_id}}/agents/{{agent_id}}/conversations/{{conversation_id}}/new"
    auth_app.add_api_route(path, planted, methods=["GET"])
    assert _private_but_unchecked(auth_app) == {("GET", path)}
    guarded, _ = _classify(auth_app)
    assert ("GET", path) in guarded  # so the generated matrix would include it
    client, _ = tenants.teammates["member"]
    response = client.get(_fill(path, tenants.b_workspace, tenants.b_children))
    assert (response.status_code, response.json()) == (200, 1)  # the attack would fail


def test_a_parameter_without_a_real_object_fails() -> None:
    """The attacks need real ids: an unknown parameter cannot be filled in."""
    with pytest.raises(KeyError):
        _fill("/{workspace_id}/x/{new_id}", "w", {"agent_id": "a", "version_id": "v"})


@pytest.mark.db
@pytest.mark.parametrize("path", GET_PATHS)
def test_reading_your_own_workspace_shows_only_that_workspace(tenants, path) -> None:
    """Collections have no id to attack, so look at what they return."""
    response = tenants.a.get(_fill(path, tenants.a_workspace, tenants.a_children))
    assert response.status_code == 200
    _assert_no_tenant_data(tenants, response)
    response = tenants.b.get(_fill(path, tenants.b_workspace, tenants.b_children))
    assert response.status_code == 200
    for other in (
        "B other agent",
        tenants.b_other_workspace,
        tenants.b_other_children["agent_id"],
        tenants.b_other_children["conversation_id"],
        tenants.a_workspace,
        tenants.a_children["agent_id"],
        tenants.a_children["conversation_id"],
        "A message",
    ):
        assert other not in response.text


@pytest.mark.db
def test_archived_agent_list_shows_only_the_workspace_in_the_path(tenants) -> None:
    for workspace, children in (
        (tenants.b_workspace, tenants.b_children),
        (tenants.b_other_workspace, tenants.b_other_children),
    ):
        url = f"{PREFIX}/{workspace}/agents/{children['agent_id']}/archive"
        assert tenants.b.post(url).status_code == 200
    page = tenants.b.get(f"{PREFIX}/{tenants.b_workspace}/agents?archived=true").json()
    assert [item["id"] for item in page["items"]] == [tenants.b_children["agent_id"]]
    assert page["total"] == 1


@pytest.mark.db
@pytest.mark.parametrize(("verb", "path"), MATRIX)
def test_outsider_with_an_invalid_body_still_gets_404(tenants, verb, path) -> None:
    """Validation must not answer before the membership check."""
    url = _fill(path, tenants.b_workspace, tenants.b_children)
    response = tenants.a.request(verb, url, json={"name": "", "role": "x"})
    assert response.status_code == 404


@pytest.mark.db
@pytest.mark.parametrize(("verb", "path"), MATRIX)
def test_signed_out_caller_gets_401(tenants, make_client, verb, path) -> None:
    url = _fill(path, tenants.b_workspace, tenants.b_children)
    assert make_client().request(verb, url, json=BODY).status_code == 401


@pytest.mark.db
@pytest.mark.parametrize("path", sorted({path for _, path in MATRIX}))
def test_other_verbs_are_not_served(tenants, path) -> None:
    url = _fill(path, tenants.b_workspace, tenants.b_children)
    for verb in VERBS - {v for v, p in MATRIX if p == path}:
        assert tenants.a.request(verb, url, json=BODY).status_code == 405, (verb, path)


@pytest.mark.db
def test_list_never_shows_another_tenants_workspace(tenants) -> None:
    for query in ("", f"?user_id={tenants.b_id}", f"?workspace_id={tenants.b_workspace}"):
        response = tenants.a.get(PREFIX + query)
        assert len(response.json()) == 1
        _assert_no_tenant_data(tenants, response)


@pytest.mark.db
def test_snapshot_sees_every_tenant_table(tenants, db_session) -> None:
    snapshot = _snapshot(db_session)
    names = {"users", "sessions", "workspaces", "memberships", "agents", "agent_versions"}
    names |= {"conversations", "messages"}
    assert names <= set(snapshot)
    assert all(snapshot[name] for name in names)
