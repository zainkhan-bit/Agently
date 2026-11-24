"""Agents and their immutable configuration versions."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

ACTIVE, PAUSED, ARCHIVED = "active", "paused", "archived"
# The only list of status values: the check constraint below is built from it.
STATUSES = (ACTIVE, PAUSED, ARCHIVED)


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Belongs to one workspace. Its configuration is the version numbered current_version."""

    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(status) for status in STATUSES)})", name="status_valid"
        ),
        Index("ix_agents_workspace_id_created_at", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class AgentVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One saved configuration. Never changed after it is written, except by SET NULL."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "number"),
        CheckConstraint("number >= 1", name="number_positive"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(1000))
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    # Always empty until Slice 3.1 defines real models.
    model: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
