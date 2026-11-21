"""Workspaces (tenants) and the memberships that link users to them."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.model_mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.identity.models import User

ROLES = ("owner", "member")


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One user's role in one workspace. Deleting either side deletes the membership."""

    __tablename__ = "memberships"
    __table_args__ = (
        # One membership per (user, workspace); also serves "which workspaces is this user in".
        UniqueConstraint("user_id", "workspace_id"),
        # A check constraint (not a PG enum) so adding a role later is a simple constraint swap.
        CheckConstraint("role IN ('owner', 'member')", name="role_valid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    user: Mapped[User] = relationship()
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
