"""Login and signup throttling over HTTP."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.modules.identity import passwords
from app.modules.identity.models import AuthThrottleEvent, UserSession
from tests.auth_helpers import login, register

pytestmark = pytest.mark.db

WRONG = "wrong password 123"


@pytest.fixture
def account(make_client):
    register(make_client("198.51.100.200"))
    return "a@example.com"


def fail(client, email: str = "a@example.com") -> int:
    return login(client, email=email, password=WRONG).status_code


def test_account_and_ip_pair_limit_blocks_even_the_right_password(
    account, configure, make_client, db_session
) -> None:
    configure(login_limit_per_account_ip=3)
    client = make_client()
    assert [fail(client) for _ in range(4)] == [401, 401, 401, 429]
    sessions = db_session.scalar(select(func.count()).select_from(UserSession))
    response = login(client)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert db_session.scalar(select(func.count()).select_from(UserSession)) == sessions


def test_owner_can_log_in_from_another_ip_while_one_ip_is_blocked(
    account, configure, make_client
) -> None:
    configure(login_limit_per_account_ip=3)
    attacker = make_client("198.51.100.1")
    assert [fail(attacker) for _ in range(4)][-1] == 429
    assert login(make_client("198.51.100.2")).status_code == 200


def test_account_ceiling_holds_across_ips(account, configure, make_client) -> None:
    configure(login_limit_per_account=3)
    results = [fail(make_client(f"198.51.100.{n}")) for n in range(4)]
    assert results == [401, 401, 401, 429]


def test_unknown_emails_are_throttled_like_real_ones(configure, api) -> None:
    configure(login_limit_per_account_ip=3)
    results = [fail(api, "nobody@example.com") for _ in range(4)]
    assert results == [401, 401, 401, 429]


def test_ip_limit_holds_across_accounts(configure, api) -> None:
    configure(login_limit_per_ip=3)
    results = [fail(api, f"user{n}@example.com") for n in range(4)]
    assert results == [401, 401, 401, 429]


def test_success_does_not_reset_the_ip_count(account, configure, make_client) -> None:
    configure(login_limit_per_ip=3)
    client = make_client()
    assert [fail(client, "x@example.com"), fail(client, "y@example.com")] == [401, 401]
    assert login(client).status_code == 200  # the attacker's own account
    assert fail(client, "z@example.com") == 401
    assert fail(client, "w@example.com") == 429


def test_success_clears_the_account_count(account, configure, make_client) -> None:
    configure(login_limit_per_account_ip=3, login_limit_per_account=3)
    client = make_client()
    assert [fail(client), fail(client)] == [401, 401]
    assert login(client).status_code == 200
    assert [fail(client) for _ in range(4)] == [401, 401, 401, 429]


def test_hammering_while_throttled_does_not_extend_the_window(
    account, configure, make_client, advance
) -> None:
    configure(login_limit_per_account_ip=3)
    client = make_client()
    for _ in range(3):
        fail(client)
    for minute in range(1, 15):
        advance(minutes=minute)
        assert fail(client) == 429
    advance(minutes=15)
    assert login(client).status_code == 200


def test_attempt_is_recorded_before_the_password_is_verified(
    account, api, db_session, monkeypatch
) -> None:
    seen = []

    def verify(*_args) -> bool:
        seen.append(db_session.scalar(select(func.count()).select_from(AuthThrottleEvent)))
        return False

    before = db_session.scalar(select(func.count()).select_from(AuthThrottleEvent))
    monkeypatch.setattr(passwords, "verify_password", verify)
    fail(api)
    assert seen == [before + 3]


def test_throttled_login_does_not_verify_the_password(account, configure, api, monkeypatch) -> None:
    configure(login_limit_per_ip=1)
    fail(api)
    monkeypatch.setattr(passwords, "verify_password", lambda *_: pytest.fail("verified"))
    assert fail(api) == 429


def test_signup_limit(configure, api, make_client) -> None:
    configure(signup_limit_per_ip=5)
    codes = [register(api, email=f"user{n}@example.com").status_code for n in range(6)]
    assert codes == [201] * 5 + [429]
    other = register(make_client("198.51.100.9"), email="other@example.com")
    assert other.status_code == 201


def test_failed_signups_count_too(configure, api) -> None:
    configure(signup_limit_per_ip=2)
    codes = [register(api).status_code for _ in range(3)]
    assert codes == [201, 409, 429]


def test_spoofed_forwarded_header_does_not_dodge_the_ip_limit(configure, api) -> None:
    configure(login_limit_per_ip=2)
    codes = [
        login(
            api,
            email=f"user{n}@example.com",
            password=WRONG,
            headers={"X-Forwarded-For": f"192.0.2.{n}"},
        ).status_code
        for n in range(3)
    ]
    assert codes == [401, 401, 429]


def test_attempts_over_the_pair_limit_never_touch_the_account_count(
    account, configure, make_client, db_session
) -> None:
    """One flooding IP must not use up the account ceiling, even for a moment."""
    configure(login_limit_per_account_ip=1)
    client = make_client()
    fail(client)
    added = []
    event.listen(db_session, "before_flush", lambda s, *_: added.extend(s.new))
    assert fail(client) == 429
    assert "login_account" not in {row.scope for row in added}
    assert added


def test_parallel_guesses_see_each_other(auth_app, configure, make_client, test_engine) -> None:
    """Separate connections, as in production: at most the limit gets a password check."""
    configure(login_limit_per_account_ip=3)
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def real_get_db():
        with factory() as session:
            yield session

    auth_app.dependency_overrides[get_db] = real_get_db
    try:
        with ThreadPoolExecutor(10) as pool:
            codes = list(pool.map(lambda _: fail(make_client()), range(10)))
        assert set(codes) <= {401, 429}
        assert codes.count(401) <= 3
        # Rows were committed: a fresh connection sees them.
        with factory() as session:
            rows = session.scalar(select(func.count()).select_from(AuthThrottleEvent))
        assert rows == 3 * codes.count(401)
    finally:
        with factory() as session:
            session.execute(delete(AuthThrottleEvent))
            session.commit()


def test_trusted_proxy_address_is_the_throttled_one(configure, api) -> None:
    configure(trusted_proxy_hops=1, login_limit_per_ip=1)

    def attempt(forwarded: str) -> int:
        headers = {"X-Forwarded-For": forwarded}
        return login(api, email="x@example.com", password=WRONG, headers=headers).status_code

    assert attempt("192.0.2.1, 198.51.100.1") == 401
    assert attempt("192.0.2.2, 198.51.100.1") == 429
    assert attempt("192.0.2.1, 198.51.100.2") == 401
