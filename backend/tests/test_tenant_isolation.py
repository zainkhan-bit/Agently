"""Tenant isolation matrix: the Phase 1 exit-gate proof.

Generated from the registered routes. Every route must either resolve a workspace through
``get_workspace_context`` or be listed below as belonging to no workspace, whatever its path looks
like, so a new route cannot be missed. Workspace routes are then attacked by another tenant.
"""

import re
import uuid

import pytest
from fastapi.routing import iter_route_contexts
from sqlalchemy import text

from app.main import create_app
from app.models import Base
from app.modules.identity.router import PUBLIC_ROUTES
from app.modules.workspaces.dependencies import get_workspace_context
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
def tenants(make_client):
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
    t.b_children = {"user_id": t.b_id}
    return t


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


def _error(response) -> dict:
    return {k: v for k, v in response.json()["error"].items() if k != "request_id"}


def _assert_no_tenant_data(tenants, response) -> None:
    for secret in ("tenant-b", "B private name", tenants.b_id, tenants.b_workspace):
        assert secret not in response.text


@pytest.mark.db
@pytest.mark.parametrize("child", ["own", "theirs"])
@pytest.mark.parametrize(("verb", "path"), MATRIX)
def test_outsider_gets_404_and_no_data(tenants, db_session, verb, path, child) -> None:
    """User A, signed in, targets user B's workspace."""
    children = tenants.b_children if child == "theirs" else {"user_id": tenants.a_id}
    children = {**tenants.b_children, **children}
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
@pytest.mark.parametrize(("verb", "path"), CHILD_MATRIX)
def test_own_workspace_does_not_open_another_tenants_objects(
    tenants, db_session, verb, path
) -> None:
    """User A, an owner, uses their own workspace id with the id of something of B's."""
    before = _snapshot(db_session)
    url = _fill(path, tenants.a_workspace, tenants.b_children)
    response = tenants.a.request(verb, url, json=BODY)
    assert response.status_code == 404
    _assert_no_tenant_data(tenants, response)
    assert _snapshot(db_session) == before


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
    assert {"users", "sessions", "workspaces", "memberships"} <= set(snapshot)
    assert all(snapshot[name] for name in ("users", "workspaces", "memberships"))
