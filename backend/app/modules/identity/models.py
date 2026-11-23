"""User accounts and server-side authentication sessions (see ADR-0003)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.model_mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are unique regardless of letter case. Stored as entered; lookups must compare
        # lower(email) = lower(:input) so this index is used.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # never include the password hash
        return f"User(id={self.id!s})"


class UserSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A login session. Only a hash of the session token is stored, never the raw token."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    def __repr__(self) -> str:  # never include the token hash
        return f"UserSession(id={self.id!s}, user_id={self.user_id!s})"


class AuthThrottleEvent(UUIDPrimaryKeyMixin, Base):
    """One counted login or signup attempt. Keys are hashes: no plaintext email is stored."""

    __tablename__ = "auth_throttle_events"
    __table_args__ = (
        Index("ix_auth_throttle_events_lookup", "scope", "key_hash", "created_at"),
        Index("ix_auth_throttle_events_created_at", "created_at"),
    )

    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set from app.core.clock (no server default) so counting and cleanup share one time source.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
