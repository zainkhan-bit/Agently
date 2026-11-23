"""Registration, login and logout rules.

Throttle rows are committed before anything raises: ``get_db`` rolls back on exceptions, which
would otherwise discard the record of a failed attempt.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import AuthenticationError, ConflictError, RateLimitError
from app.modules.identity import events, passwords, sessions, throttle
from app.modules.identity.events import RequestInfo
from app.modules.identity.models import User
from app.modules.workspaces import service as workspaces


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    message = "Email or password is incorrect."


class RegistrationFailedError(ConflictError):
    code = "registration_failed"
    message = "Could not create an account with these details."


def _find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == func.lower(email)))


def register(db: Session, email: str, password: str, info: RequestInfo) -> tuple[User, str]:
    """Create an account, its personal workspace and first session. Returns user and raw token."""
    if throttle.record_attempt(db, throttle.signup_limits(info.ip)) is None:
        events.log("signup_throttled", info)
        raise RateLimitError()
    if _find_user(db, email) is not None:
        raise RegistrationFailedError()
    user = User(email=email, password_hash=passwords.hash_password(password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # a concurrent registration won the unique index
        db.rollback()
        raise RegistrationFailedError() from exc
    workspaces.add_workspace(db, user.id, workspaces.PERSONAL_WORKSPACE_NAME)
    token = sessions.create_session(db, user)
    db.commit()
    events.log("register", info, user.id)
    return user, token


def login(db: Session, email: str, password: str, info: RequestInfo) -> tuple[User, str]:
    """Check credentials and start a new session. Returns the user and the raw session token."""
    limits = throttle.login_limits(email, info.ip)
    event_ids = throttle.record_attempt(db, limits)
    user = _find_user(db, email)
    user_id = user.id if user else None
    if event_ids is None:
        events.log("login_throttled", info, user_id)
        raise RateLimitError()
    password_ok = passwords.verify_password(user.password_hash if user else None, password)
    if user is None or not password_ok:
        events.log("login_failed", info, user_id)
        raise InvalidCredentialsError()
    throttle.clear_after_login(db, limits, event_ids)
    token = sessions.create_session(db, user)
    db.commit()
    events.log("login_succeeded", info, user.id)
    return user, token


def logout(db: Session, token: str | None, info: RequestInfo) -> None:
    """Revoke the session if it is active. Safe to call without one."""
    active = sessions.find_active_session(db, token)
    user_id = active.user_id if active else None
    if active is not None:
        active.revoked_at = clock.now()
        db.commit()
    events.log("logout", info, user_id)
