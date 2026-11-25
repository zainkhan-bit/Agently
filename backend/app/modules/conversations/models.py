"""Private conversations between one person and one agent."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

USER, ASSISTANT = "user", "assistant"
# The only list of role values: the check constraint below is built from it.
ROLES = (USER, ASSISTANT)


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Seen only by its creator. ``updated_at`` is the time of the last message."""

    __tablename__ = "conversations"
    __table_args__ = (
        # The agent is one of this workspace, and the person is a member of it. The second key
        # also deletes a person's conversations when they leave or are removed (ADR-0005).
        ForeignKeyConstraint(
            ["agent_id", "workspace_id"],
            ["agents.id", "agents.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["memberships.user_id", "memberships.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "agent_id"),  # for the messages' foreign key
        CheckConstraint("message_count >= 0", name="message_count_not_negative"),
        Index("ix_conversations_agent_id_user_id_updated_at", "agent_id", "user_id", "updated_at"),
        Index("ix_conversations_user_id_workspace_id", "user_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Also the sequence number of the last message.
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StoredMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Private text. Never changed after it is written."""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "agent_id"],
            ["conversations.id", "conversations.agent_id"],
            ondelete="CASCADE",
        ),
        # A version of the same agent. Cascades because versions are only deleted with their
        # agent: without it, this key could block deleting the agent.
        ForeignKeyConstraint(
            ["agent_id", "agent_version"],
            ["agent_versions.agent_id", "agent_versions.number"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("conversation_id", "sequence"),  # also serves "the last N messages"
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(f"role IN ({', '.join(repr(role) for role in ROLES)})", name="role_valid"),
        CheckConstraint(
            f"(role = '{ASSISTANT}') = (agent_version IS NOT NULL)", name="version_of_assistant"
        ),
        CheckConstraint("content <> ''", name="content_not_empty"),
        Index("ix_messages_agent_id_agent_version", "agent_id", "agent_version"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Which configuration produced the answer. Empty for what the person wrote.
    agent_version: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
