"""State-changing requests need an allowlisted Origin header."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

ALLOWED = "http://localhost:3000"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOWED_ORIGINS", f'["{ALLOWED}"]')
    get_settings.cache_clear()
    app = create_app()

    @app.api_route("/api/probe", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def probe() -> dict[str, bool]:
        return {"ok": True}

    yield TestClient(app)
    get_settings.cache_clear()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "origin",
    [None, "null", "https://evil.example", "http://localhost:3001", ALLOWED + ".evil.example"],
)
def test_unsafe_request_without_allowed_origin_is_rejected(client, method, origin) -> None:
    headers = {} if origin is None else {"Origin": origin}
    response = client.request(method, "/api/probe", headers=headers)
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "origin_rejected"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_custom_header_is_not_a_substitute_for_origin(client) -> None:
    response = client.post("/api/probe", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 403


def test_repeated_origin_headers_are_rejected(client) -> None:
    headers = [("Origin", ALLOWED), ("Origin", "https://evil.example")]
    assert client.post("/api/probe", headers=headers).status_code == 403


def test_allowed_origin_passes(client) -> None:
    assert client.post("/api/probe", headers={"Origin": ALLOWED}).status_code == 200


def test_safe_request_needs_no_origin(client) -> None:
    assert client.get("/api/probe").status_code == 200
    assert client.get("/api/health").status_code == 200
