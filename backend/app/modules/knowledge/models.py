"""Knowledge sources: files a workspace gave one of its agents. Shared by the workspace's members.

A record holds no file content. The file itself is in private storage under a random name.
"""

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
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
        # For the chunks' foreign key: a chunk names the workspace and agent of its own source.
        UniqueConstraint("id", "agent_id", "workspace_id"),
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


class KnowledgeChunk(UUIDPrimaryKeyMixin, Base):
    """A piece of a source's text. Private: never logged. Deleted with its source."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "agent_id", "workspace_id"],
            [
                "knowledge_sources.id",
                "knowledge_sources.agent_id",
                "knowledge_sources.workspace_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("source_id", "sequence"),
        CheckConstraint("sequence >= 0", name="sequence_not_negative"),
        CheckConstraint("page IS NULL OR page >= 1", name="page_positive"),
        CheckConstraint("content <> ''", name="content_not_empty"),
        Index("ix_knowledge_chunks_agent_id", "agent_id"),
        Index("ix_knowledge_chunks_search_english", "search_english", postgresql_using="gin"),
        Index("ix_knowledge_chunks_search_simple", "search_simple", postgresql_using="gin"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Copies of the source's, kept equal by the foreign key, so that retrieval can filter here.
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)  # PDFs only
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Search forms of the text, kept by PostgreSQL itself: stemmed English, and exact words for
    # everything English stemming does not know (Roman Urdu, names, codes).
    search_english: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english'::regconfig, content)", persisted=True)
    )
    search_simple: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, content)", persisted=True)
    )
