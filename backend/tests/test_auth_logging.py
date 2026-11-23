"""Auth events are logged with context and without secrets."""

import hashlib
import logging

import pytest

from tests.auth_helpers import COOKIE, PASSWORD, login, me, register

pytestmark = pytest.mark.db

WRONG = "wrong password 123"


def test_auth_events_are_logged_without_secrets(api, configure, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    configure(login_limit_per_account_ip=1)
    user_id = register(api, email="Secret.Person@example.com").json()["id"]
    tokens = [api.cookies[COOKIE]]
    login(api, email="secret.person@example.com")
    tokens.append(api.cookies[COOKIE])
    login(api, email="secret.person@example.com", password=WRONG)
    login(api, email="secret.person@example.com", password=WRONG)
    login(api, email="nobody@example.com", password=WRONG)
    me(api)
    register(api, email="bad", password="short-secret")
    request_id = api.post("/api/auth/logout").headers["X-Request-ID"]

    lines = [r.getMessage() for r in caplog.records if r.name == "app.auth.events"]
    events = [line.split()[0] for line in lines]
    assert events == [
        "event=register",
        "event=login_succeeded",
        "event=login_failed",
        "event=login_throttled",
        "event=login_failed",
        "event=logout",
    ]
    assert all(" ip=203.0.113.1 " in line and " request_id=" in line for line in lines)
    assert lines[-1].endswith(f"request_id={request_id}")
    assert [f"user_id={user_id}" in line for line in lines] == [True] * 4 + [False, True]

    hashes = [hashlib.sha256(token.encode()).hexdigest() for token in tokens]
    for secret in [PASSWORD, WRONG, "short-secret", *tokens, *hashes]:
        assert secret not in caplog.text
    assert "person@example.com" not in caplog.text.lower()
    assert "nobody@example.com" not in caplog.text


def test_throttled_signup_is_logged(api, configure, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.auth.events")
    configure(signup_limit_per_ip=1)
    register(api)
    register(api, email="b@example.com")
    assert "event=signup_throttled user_id=None" in caplog.text
