"""Sliding-window attempt limits stored in PostgreSQL.

An attempt is recorded and committed before it is counted, so parallel attempts see each other.
This module commits: callers must not have unrelated uncommitted work in the session.
"""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.client_ip import throttle_network
from app.core.config import get_settings
from app.modules.identity.models import AuthThrottleEvent

LOGIN_ACCOUNT = "login_account"
LOGIN_ACCOUNT_IP = "login_account_ip"
LOGIN_IP = "login_ip"
SIGNUP_IP = "signup_ip"


@dataclass(frozen=True)
class Limit:
    scope: str
    key_hash: str
    maximum: int
    window: timedelta


def _limit(scope: str, maximum: int, window_minutes: int, *key: str) -> Limit:
    digest = hashlib.sha256("\x00".join((scope, *key)).encode()).hexdigest()
    return Limit(scope, digest, maximum, timedelta(minutes=window_minutes))


def login_limits(email: str, ip: str) -> list[Limit]:
    settings = get_settings()
    email = email.strip().lower()
    network = throttle_network(ip)
    window = settings.login_window_minutes
    return [
        # Order matters: an address over its own limits must never reach the account counter.
        _limit(LOGIN_IP, settings.login_limit_per_ip, window, network),
        _limit(LOGIN_ACCOUNT_IP, settings.login_limit_per_account_ip, window, email, network),
        _limit(LOGIN_ACCOUNT, settings.login_limit_per_account, window, email),
    ]


def signup_limits(ip: str) -> list[Limit]:
    settings = get_settings()
    network = throttle_network(ip)
    window = settings.signup_window_minutes
    return [_limit(SIGNUP_IP, settings.signup_limit_per_ip, window, network)]


def record_attempt(session: Session, limits: Sequence[Limit]) -> dict[str, uuid.UUID] | None:
    """Record one attempt per limit. Returns the event ids by scope, or None when throttled.

    A throttled attempt leaves no rows, so repeating it cannot extend the window.
    """
    _delete_expired(session)
    ids: dict[str, uuid.UUID] = {}
    for limit in limits:
        ids[limit.scope] = uuid.uuid4()
        session.add(
            AuthThrottleEvent(
                id=ids[limit.scope],
                scope=limit.scope,
                key_hash=limit.key_hash,
                created_at=clock.now(),
            )
        )
        session.commit()
        if _count(session, limit) > limit.maximum:
            # One delete per limit, in the same order as clear_after_login, so they cannot deadlock.
            for event_id in ids.values():
                session.execute(delete(AuthThrottleEvent).where(AuthThrottleEvent.id == event_id))
            session.commit()
            return None
    return ids


def clear_after_login(
    session: Session, limits: Sequence[Limit], event_ids: dict[str, uuid.UUID]
) -> None:
    """Forget the account's failures, but only this attempt's own IP row. Does not commit."""
    for limit in limits:
        if limit.scope == LOGIN_IP:
            condition = AuthThrottleEvent.id == event_ids[LOGIN_IP]
        else:
            condition = (AuthThrottleEvent.scope == limit.scope) & (
                AuthThrottleEvent.key_hash == limit.key_hash
            )
        session.execute(delete(AuthThrottleEvent).where(condition))


def _count(session: Session, limit: Limit) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(AuthThrottleEvent)
        .where(
            AuthThrottleEvent.scope == limit.scope,
            AuthThrottleEvent.key_hash == limit.key_hash,
            AuthThrottleEvent.created_at > clock.now() - limit.window,
        )
    )
    return count or 0


def _delete_expired(session: Session) -> None:
    settings = get_settings()
    longest = timedelta(minutes=max(settings.login_window_minutes, settings.signup_window_minutes))
    session.execute(
        delete(AuthThrottleEvent).where(AuthThrottleEvent.created_at <= clock.now() - longest)
    )
