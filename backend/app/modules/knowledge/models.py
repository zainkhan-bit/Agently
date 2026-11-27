"""Knowledge sources: files a workspace gave one of its agents. Shared by the workspace's members.

A record holds no file content. The file itself is in private storage under a random name.
"""

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_mixins import TimestampMixin, UUIDPrimaryKeyMixin

PDF, DOCX, TXT, MD = "pdf", "docx", "txt", "md"
# The only list of kinds: the check constraint below is built from it.
KINDS = (PDF, DOCX, TXT, MD)
PENDING, PROCESSING, READY, FAILED = "pending", "processing", "ready", "failed"
STATUSES = (PENDING, PROCESSING, READY, FAILED)
STORAGE_NAME_PATTERN = "^[0-9a-f]{32}$"


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class KnowledgeSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        # The agent is one of this workspace's; deleting it deletes its sources (and the files,
        # which the code removes after the commit).
        ForeignKeyConstraint(
            ["agent_id", "workspace_id"],
            ["agents.id", "agents.workspace_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_one_of("kind", KINDS), name="kind_valid"),
        CheckConstraint(_one_of("status", STATUSES), name="status_valid"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint(f"storage_name ~ '{STORAGE_NAME_PATTERN}'", name="storage_name_random"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        Index("ix_knowledge_sources_agent_id_created_at", "agent_id", "created_at"),
        Index("ix_knowledge_sources_workspace_id", "workspace_id"),
        Index("uq_knowledge_sources_agent_id_sha256", "agent_id", "sha256", unique=True),
        Index("uq_knowledge_sources_storage_name", "storage_name", unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Who uploaded it; kept when that person's account goes.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # The name the person gave it. Shown only; never part of a path, a log line or an error.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_name: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50))  # from our own errors only
