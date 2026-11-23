"""Register, login, logout and /me over HTTP."""

import hashlib
from unittest.mock import Mock

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.modules.identity import passwords, service
from app.modules.identity.models import AuthThrottleEvent, User, UserSession
from tests.auth_helpers import COOKIE, PASSWORD, login, me, register

pytestmark = pytest.mark.db


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def use_cookie(client, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(COOKIE, token)


def test_register_then_me_then_logout(api, db_session) -> None:
    response = register(api)
    assert response.status_code == 201
    assert set(response.json()) == {"id", "email", "created_at"}
    assert me(api).json() == response.json()

    token = api.cookies[COOKIE]
    assert api.post("/api/auth/logout").status_code == 204
    assert COOKIE not in api.cookies
    assert me(api).status_code == 401

    use_cookie(api, token)  # replay the old cookie
    assert me(api).status_code == 401
    assert db_session.scalars(select(UserSession)).one().revoked_at is not None


@pytest.mark.parametrize("action", [register, login])
def test_session_cookie_flags(make_client, action) -> None:
    if action is login:
        register(make_client())
    header = action(make_client()).headers["set-cookie"].lower()
    attributes = {part.strip() for part in header.split(";")[1:]}
    assert {"httponly", "samesite=lax", "secure", "path=/", "max-age=1209600"} <= attributes
    assert not any(part.startswith("domain") for part in attributes)


def test_development_cookie_is_not_secure(api, configure) -> None:
    configure(environment="development", session_cookie_secure="false")
    header = register(api).headers["set-cookie"].lower()
    assert "secure" not in header
    assert "httponly" in header and "samesite=lax" in header


@pytest.mark.parametrize("length", [11, 129])
def test_password_length_is_checked_before_hashing(api, monkeypatch, length) -> None:
    monkeypatch.setattr(passwords, "hash_password", lambda _: pytest.fail("hashed"))
    response = register(api, password="x" * length)
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert details[0]["msg"] == "Password must be 12 to 128 characters."
    assert "x" * 11 not in response.text


@pytest.mark.parametrize("length", [12, 128])
def test_password_length_limits_are_inclusive(api, length) -> None:
    assert register(api, password="x" * length).status_code == 201


@pytest.mark.parametrize(
    "email",
    [
        "no-at.example.com",
        "a@b@example.com",
        "a@nodot",
        "@example.com",
        "a\x00@b.com",
        "",
        "é@example.com",
        "a" * 309 + "@example.com",
    ],
)
def test_invalid_email_is_rejected(api, email) -> None:
    assert register(api, email=email).status_code == 422


def test_duplicate_email_is_a_generic_failure(api, db_session) -> None:
    register(api, email="a@example.com")
    response = register(api, email="  A@EXAMPLE.com ")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "registration_failed"
    assert "example.com" not in response.text.lower()
    assert "set-cookie" not in response.headers
    assert count(db_session, User) == 1


def test_concurrent_duplicate_is_the_same_failure(api, db_session, monkeypatch) -> None:
    register(api)
    monkeypatch.setattr(service, "_find_user", lambda *_: None)  # lost the race
    response = register(api)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "registration_failed"
    assert count(db_session, User) == 1


def test_unique_email_is_enforced_by_the_database(api, db_session) -> None:
    register(api)
    db_session.add(User(email="A@example.com", password_hash="x"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_wrong_password_and_unknown_email_look_the_same(api) -> None:
    register(api)
    wrong = login(api, password="not the password")
    unknown = login(api, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    first, second = wrong.json()["error"], unknown.json()["error"]
    assert first["code"] == second["code"] == "invalid_credentials"
    assert first["message"] == second["message"]
    assert first["details"] == second["details"]


def test_unknown_email_still_pays_for_a_hash(api, monkeypatch) -> None:
    hasher = Mock(wraps=passwords._hasher)
    monkeypatch.setattr(passwords, "_hasher", hasher)
    assert login(api, email="nobody@example.com").status_code == 401
    hasher.verify.assert_called_once()


def test_dummy_hash_never_authenticates(monkeypatch) -> None:
    monkeypatch.setattr(passwords, "_hasher", Mock(verify=Mock(return_value=True)))
    assert passwords.verify_password(None, "anything at all") is False


@pytest.mark.parametrize("path", ["register", "login"])
def test_unencodable_password_is_a_validation_error(api, path) -> None:
    body = '{"email": "a@example.com", "password": "' + "\\ud800" * 12 + '"}'
    response = api.post(
        f"/api/auth/{path}", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_oversized_body_is_rejected(api) -> None:
    assert login(api, password="x" * 100_000).status_code == 413


def test_cookie_name_and_lifetime_come_from_settings(api, configure) -> None:
    configure(session_cookie_name="other_name", session_ttl_days=1)
    header = register(api).headers["set-cookie"]
    assert header.startswith("other_name=")
    assert "Max-Age=86400" in header
    assert me(api).status_code == 200


def test_logout_with_an_expired_session_succeeds(api, advance) -> None:
    register(api)
    token = api.cookies[COOKIE]
    advance(days=15)
    use_cookie(api, token)
    response = api.post("/api/auth/logout")
    assert response.status_code == 204
    assert f'{COOKIE}=""; ' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_login_ignores_and_replaces_an_existing_token(make_client, db_session) -> None:
    client = make_client()
    register(client)
    old = client.cookies[COOKIE]
    login(client)
    new = client.cookies[COOKIE]
    assert new != old
    assert me(client).status_code == 200


def test_login_never_adopts_a_client_chosen_token(api, make_client, db_session) -> None:
    register(make_client())
    planted = "attacker-chosen-token"
    use_cookie(api, planted)
    response = login(api)
    assert planted not in response.headers["set-cookie"]
    use_cookie(api, planted)
    assert me(api).status_code == 401


@pytest.mark.parametrize("cookie", [None, "unknown-token"])
def test_logout_without_a_session_succeeds(api, cookie) -> None:
    if cookie:
        use_cookie(api, cookie)
    response = api.post("/api/auth/logout")
    assert response.status_code == 204
    assert f'{COOKIE}=""; ' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize("cookie", [None, "", "unknown-token"])
def test_me_needs_a_known_token(api, cookie) -> None:
    if cookie is not None:
        use_cookie(api, cookie)
    assert me(api).status_code == 401


def test_session_expires_after_14_days_despite_activity(api, advance) -> None:
    register(api)
    token = api.cookies[COOKIE]
    advance(days=13, hours=23, minutes=59)
    use_cookie(api, token)
    response = me(api)
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    advance(days=14, seconds=1)
    assert me(api).status_code == 401


@pytest.mark.parametrize("origin", ["https://evil.example", "null"])
def test_cross_origin_login_creates_no_session(api, make_client, db_session, origin) -> None:
    register(make_client())
    before = count(db_session, UserSession)
    response = login(api, headers={"Origin": origin})
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert count(db_session, UserSession) == before


def test_cross_origin_logout_does_not_revoke(api) -> None:
    register(api)
    response = api.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert me(api).status_code == 200


def test_only_hashes_are_stored(api, db_session) -> None:
    register(api)
    token = api.cookies[COOKIE]
    user = db_session.scalars(select(User)).one()
    assert user.password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(user.password_hash, PASSWORD)
    stored = db_session.scalars(select(UserSession)).one()
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    for table in (User, UserSession, AuthThrottleEvent):
        dump = db_session.scalars(text(f"SELECT t::text FROM {table.__tablename__} t")).all()  # noqa: S608
        assert dump
        assert PASSWORD not in "".join(dump)
        assert token not in "".join(dump)


def test_short_login_password_is_an_ordinary_failure(api) -> None:
    register(api)
    response = login(api, password="short")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_overlong_login_password_is_never_hashed(api, monkeypatch) -> None:
    monkeypatch.setattr(passwords, "verify_password", lambda *_: pytest.fail("hashed"))
    assert login(api, password="x" * 129).status_code == 422


def test_longest_allowed_email(api) -> None:
    assert register(api, email="a" * 308 + "@example.com").status_code == 201


def test_corrupt_password_hash_is_a_failed_login(api, db_session) -> None:
    register(api)
    db_session.scalars(select(User)).one().password_hash = "corrupt"
    db_session.commit()
    assert login(api).status_code == 401
