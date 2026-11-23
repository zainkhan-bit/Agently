"""Every route requires a session unless it is on the explicit public list."""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts

from app.main import create_app
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.router import PUBLIC_ROUTES


def _requires_user(dependant: Dependant) -> bool:
    return any(
        child.call is get_current_user or _requires_user(child) for child in dependant.dependencies
    )


def unprotected(app: FastAPI) -> set[tuple[str, str]]:
    found = set()
    # Not app.routes: FastAPI resolves included routers lazily, so their routes are not in it.
    for route in iter_route_contexts(app.routes):
        dependant = getattr(route, "dependant", None)
        if dependant is not None and _requires_user(dependant):
            continue
        methods = getattr(route, "methods", None) or {"ANY"}  # mounts, websockets
        found |= {(method, getattr(route, "path", "?")) for method in methods - {"HEAD"}}
    return found


def test_unprotected_routes_are_exactly_the_public_list() -> None:
    assert unprotected(create_app()) == PUBLIC_ROUTES


def test_a_new_route_without_a_session_check_is_caught() -> None:
    app = create_app()
    app.get("/api/direct")(lambda: {})
    router = APIRouter(prefix="/nested")
    router.post("/thing")(lambda: {})
    app.include_router(router, prefix="/api")
    added = unprotected(app) - PUBLIC_ROUTES
    assert added == {("GET", "/api/direct"), ("POST", "/api/nested/thing")}


@pytest.mark.db
def test_anonymous_requests_to_private_routes_are_rejected(api, auth_app) -> None:
    private = {
        (method, route.path)
        for route in iter_route_contexts(auth_app.routes)
        for method in route.methods - {"HEAD"}
        if "{" not in route.path
    } - PUBLIC_ROUTES
    assert ("GET", "/api/auth/me") in private
    for method, path in private:
        assert api.request(method, path).status_code == 401, (method, path)
