import logging

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core import database
from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def reset_caches():
    # The session factory caches an engine too; clear it so no test reuses a stale one.
    get_settings.cache_clear()
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()


def test_liveness_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_database_reachable(client, monkeypatch) -> None:
    monkeypatch.setattr(database, "check_database", lambda: "ok")
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readiness_reports_not_configured(client, monkeypatch, reset_caches) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        get_settings(), "database_url", None
    )  # also ignore any local backend/.env value
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "not_configured"


def test_readiness_reports_unreachable_database_without_leaking_secret(
    client, monkeypatch, reset_caches, caplog
) -> None:
    secret = "s3cret-pw-do-not-log"
    settings = get_settings()
    # Port 1 on localhost refuses connections quickly.
    monkeypatch.setattr(
        settings,
        "database_url",
        SecretStr(f"postgresql+psycopg://agently:{secret}@127.0.0.1:1/agently"),
    )
    monkeypatch.setattr(settings, "database_connect_timeout_seconds", 1)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
    assert secret not in response.text
    assert secret not in caplog.text


def test_settings_repr_hides_database_password(monkeypatch, reset_caches) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:hunter2@localhost/db")
    assert "hunter2" not in repr(get_settings())


def test_unknown_route_uses_standard_error_format(client) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]


def test_request_id_is_echoed_when_safe(client) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_unsafe_request_id_is_replaced(client) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "bad id\nwith newline"[:20]})
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"[:20]
    assert len(response.headers["X-Request-ID"]) == 32


def test_unexpected_error_returns_safe_message() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/boom")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "internal detail" not in response.text
