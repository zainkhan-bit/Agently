"""Server-side sessions: random token in a cookie, only its SHA-256 hash in the database."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.modules.identity.models import User, UserSession


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    """Add a new session and return its raw token. Does not commit."""
    token = secrets.token_urlsafe(32)
    expires_at = clock.now() + timedelta(days=get_settings().session_ttl_days)
    db.add(UserSession(user_id=user.id, token_hash=_hash_token(token), expires_at=expires_at))
    return token


def find_active_session(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    return db.scalar(
        select(UserSession).where(
            UserSession.token_hash == _hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > clock.now(),
        )
    )


def set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_is_secure,
    )


def clear_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_is_secure,
    )
