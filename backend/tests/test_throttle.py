"""Throttle storage: sliding windows, hashed keys, bounded size."""

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.identity import throttle
from app.modules.identity.models import AuthThrottleEvent

pytestmark = pytest.mark.db

IP = "203.0.113.1"
EMAIL = "Person@Example.com"


@pytest.fixture(autouse=True)
def limits_of_five(configure) -> None:
    configure(login_limit_per_account_ip=5)


def rows(session) -> int:
    return session.scalar(select(func.count()).select_from(AuthThrottleEvent))


def test_attempts_above_the_limit_are_throttled_and_leave_no_rows(db_session, advance) -> None:
    limits = throttle.login_limits(EMAIL, IP)
    for _ in range(5):
        assert throttle.record_attempt(db_session, limits) is not None
    before = rows(db_session)
    assert throttle.record_attempt(db_session, limits) is None
    assert rows(db_session) == before
    # Other accounts are unaffected.
    other = throttle.login_limits("other@example.com", IP)
    assert throttle.record_attempt(db_session, other) is not None


def test_attempts_outside_the_window_are_not_counted(db_session, advance) -> None:
    limits = throttle.login_limits(EMAIL, IP)
    for _ in range(5):
        throttle.record_attempt(db_session, limits)
    advance(minutes=14)
    assert throttle.record_attempt(db_session, limits) is None
    advance(minutes=15)
    assert throttle.record_attempt(db_session, limits) is not None


def test_rows_older_than_the_longest_window_are_deleted(db_session, advance) -> None:
    for n in range(10):  # spraying random emails
        throttle.record_attempt(db_session, throttle.login_limits(f"spray{n}@example.com", IP))
    assert rows(db_session) == 30
    advance(minutes=30)
    throttle.record_attempt(db_session, throttle.signup_limits(IP))
    assert rows(db_session) == 31  # newer than the longest window: kept
    advance(minutes=60)
    throttle.record_attempt(db_session, throttle.signup_limits(IP))
    assert rows(db_session) == 2


def test_agent_writes_are_counted_per_user(db_session, advance, configure) -> None:
    configure(agent_write_limit=60)
    limits = throttle.agent_write_limits(uuid.uuid4())
    for _ in range(60):
        assert throttle.record_attempt(db_session, limits) is not None
    assert throttle.record_attempt(db_session, limits) is None
    other = throttle.agent_write_limits(uuid.uuid4())
    assert throttle.record_attempt(db_session, other) is not None
    advance(minutes=10)
    assert throttle.record_attempt(db_session, limits) is not None


def test_cleanup_keeps_rows_inside_a_longer_agent_window(db_session, advance, configure) -> None:
    configure(agent_write_limit=1, agent_write_window_minutes=180)
    limits = throttle.agent_write_limits(uuid.uuid4())
    assert throttle.record_attempt(db_session, limits) is not None
    advance(minutes=120)
    throttle.record_attempt(db_session, throttle.login_limits(EMAIL, IP))
    assert throttle.record_attempt(db_session, limits) is None


def test_keys_hold_no_plaintext_email_and_ignore_case(db_session) -> None:
    throttle.record_attempt(db_session, throttle.login_limits(EMAIL, IP))
    for event in db_session.scalars(select(AuthThrottleEvent)):
        stored = f"{event.scope} {event.key_hash}".lower()
        assert "example" not in stored
        assert len(event.key_hash) == 64
    assert throttle.login_limits(EMAIL, IP) == throttle.login_limits(" person@example.COM ", IP)


def test_clearing_after_login_keeps_other_ip_rows(db_session, advance) -> None:
    limits = throttle.login_limits(EMAIL, IP)
    for _ in range(2):
        throttle.record_attempt(db_session, limits)
    event_ids = throttle.record_attempt(db_session, limits)
    throttle.clear_after_login(db_session, limits, event_ids)
    remaining = db_session.scalars(select(AuthThrottleEvent)).all()
    assert [event.scope for event in remaining] == [throttle.LOGIN_IP] * 2
    assert event_ids[throttle.LOGIN_IP] not in {event.id for event in remaining}
