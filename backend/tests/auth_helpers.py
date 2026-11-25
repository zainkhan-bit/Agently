"""Fixtures for driving the auth API over HTTP against the throwaway test database."""

from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.database import get_db
from app.main import create_app

ORIGIN = "http://localhost:3000"
PASSWORD = "correct horse battery"
COOKIE = "agently_session"


@pytest.fixture
def configure(monkeypatch) -> Iterator[Callable[..., None]]:
    """Set auth settings for one test, independent of the developer's backend/.env."""

    def apply(**values: object) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name.upper(), str(value))
        get_settings.cache_clear()

    apply(
        environment="test",
        allowed_origins=f'["{ORIGIN}"]',
        trusted_proxy_hops=0,
        session_cookie_name=COOKIE,
        session_ttl_days=14,
        session_cookie_secure="true",
        login_window_minutes=15,
        login_limit_per_account_ip=100,
        login_limit_per_account=100,
        login_limit_per_ip=100,
        signup_window_minutes=60,
        signup_limit_per_ip=100,
        agent_limit_per_workspace=50,
        agent_write_limit=1000,
        conversation_limit_per_agent=200,
        conversation_create_limit=1000,
        conversation_create_window_minutes=60,
        message_limit_per_conversation=500,
        user_message_max_characters=8_000,
        assistant_message_max_characters=32_000,
        write_lock_timeout_seconds=5,
        write_idle_timeout_seconds=30,
        agent_write_window_minutes=10,
        model_provider="mock",
        provider_timeout_seconds=20,
        mock_provider_scenario="ok",
        gemini_tier="free",
        provider_spend_limit_daily="1",
        provider_spend_limit_monthly="10",
        generation_limit_per_user=10,
        generation_limit_per_workspace=30,
        generation_window_minutes=60,
    )
    yield apply
    get_settings.cache_clear()


@pytest.fixture
def auth_app(configure, db_session: Session):
    def override() -> Iterator[Session]:
        # Same contract as get_db: uncommitted work is lost when the request fails or ends.
        try:
            yield db_session
        finally:
            db_session.rollback()
            db_session.expire_all()

    app = create_app()
    app.dependency_overrides[get_db] = override
    return app


@pytest.fixture
def make_client(auth_app) -> Callable[..., TestClient]:
    """A browser-like client. HTTPS, so Secure cookies round-trip."""

    def make(ip: str = "203.0.113.1") -> TestClient:
        return TestClient(
            auth_app,
            base_url="https://testserver",
            client=(ip, 50000),
            headers={"Origin": ORIGIN},
        )

    return make


@pytest.fixture
def api(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def advance(monkeypatch) -> Callable[..., None]:
    """Freeze the clock, then move it relative to the test's start."""
    start = clock.now()

    def move(**delta: float) -> None:
        monkeypatch.setattr(clock, "now", lambda: start + timedelta(**delta))

    move()
    return move


def register(client: TestClient, email: str = "a@example.com", password: str = PASSWORD, **kw):
    return client.post("/api/auth/register", json={"email": email, "password": password}, **kw)


def login(client: TestClient, email: str = "a@example.com", password: str = PASSWORD, **kw):
    return client.post("/api/auth/login", json={"email": email, "password": password}, **kw)


def me(client: TestClient):
    return client.get("/api/auth/me")
