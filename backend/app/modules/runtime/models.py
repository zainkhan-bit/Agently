"""A record of every attempt to answer a message. Holds no text."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_mixins import UUIDPrimaryKeyMixin

RUNNING, SUCCEEDED, FAILED = "running", "succeeded", "failed"
CANCELLED, TIMED_OUT = "cancelled", "timed_out"
# The only list of status values: the check constraint below is built from it.
STATUSES = (RUNNING, SUCCEEDED, FAILED, CANCELLED, TIMED_OUT)


class Execution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "agent_id"],
            ["conversations.id", "conversations.agent_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["agent_id", "agent_version"],
            ["agent_versions.agent_id", "agent_versions.number"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "message_sequence"],
            ["messages.conversation_id", "messages.sequence"],
            ondelete="CASCADE",
            name="fk_executions_message",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "answer_sequence"],
            ["messages.conversation_id", "messages.sequence"],
            ondelete="CASCADE",
            name="fk_executions_answer",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(status) for status in STATUSES)})", name="status_valid"
        ),
        # Success means a stored answer, and nothing else has one.
        CheckConstraint(
            f"(status = '{SUCCEEDED}') = (answer_sequence IS NOT NULL)", name="success_has_answer"
        ),
        CheckConstraint(
            f"(status = '{RUNNING}') = (finished_at IS NULL)", name="finished_unless_running"
        ),
        # One answer at a time.
        Index(
            "uq_executions_running",
            "conversation_id",
            unique=True,
            postgresql_where=f"status = '{RUNNING}'",
        ),
        # One success per message.
        Index(
            "uq_executions_succeeded",
            "conversation_id",
            "message_sequence",
            unique=True,
            postgresql_where=f"status = '{SUCCEEDED}'",
        ),
        Index("ix_executions_conversation_id", "conversation_id"),
        Index("ix_executions_agent_id_agent_version", "agent_id", "agent_version"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    message_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_sequence: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50))  # from our own errors only
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # The notice the message was sent under. Later prompts repeat it only under the same one.
    disclosure: Mapped[str] = mapped_column(String(20), nullable=False)
    # Empty = unknown. Never guessed.
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
