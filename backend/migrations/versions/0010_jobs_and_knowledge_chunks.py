"""jobs and knowledge chunks

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27

Additive. Jobs hold no content; chunks hold private document text and go with their source.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=50), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'running') = (locked_until IS NOT NULL)",
            name=op.f("ck_jobs_lease_when_running"),
        ),
        sa.CheckConstraint("kind IN ('process_source')", name=op.f("ck_jobs_kind_valid")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts", name=op.f("ck_jobs_attempts_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_status_run_after", "jobs", ["status", "run_after"], unique=False)
    op.create_index(
        "uq_jobs_open_subject",
        "jobs",
        ["kind", "subject_id"],
        unique=True,
        postgresql_where="status IN ('queued', 'running')",
    )
    # First: the chunks' foreign key needs it.
    op.create_unique_constraint(
        op.f("uq_knowledge_sources_id_agent_id_workspace_id"),
        "knowledge_sources",
        ["id", "agent_id", "workspace_id"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("content <> ''", name=op.f("ck_knowledge_chunks_content_not_empty")),
        sa.CheckConstraint(
            "page IS NULL OR page >= 1", name=op.f("ck_knowledge_chunks_page_positive")
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_knowledge_chunks_sequence_not_negative")),
        sa.ForeignKeyConstraint(
            ["source_id", "agent_id", "workspace_id"],
            [
                "knowledge_sources.id",
                "knowledge_sources.agent_id",
                "knowledge_sources.workspace_id",
            ],
            name=op.f("fk_knowledge_chunks_source_id_knowledge_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
        sa.UniqueConstraint(
            "source_id", "sequence", name=op.f("uq_knowledge_chunks_source_id_sequence")
        ),
    )
    op.create_index("ix_knowledge_chunks_agent_id", "knowledge_chunks", ["agent_id"], unique=False)
    # Sources uploaded before the worker existed are processed too.
    op.execute(
        "INSERT INTO jobs (id, kind, subject_id, status, attempts, max_attempts, run_after, "
        "created_at, updated_at) SELECT gen_random_uuid(), 'process_source', id, 'queued', 0, 3, "
        "now(), now(), now() FROM knowledge_sources WHERE status IN ('pending', 'processing')"
    )
    op.execute("UPDATE knowledge_sources SET status = 'pending' WHERE status = 'processing'")


def downgrade() -> None:
    """Deletes every job and chunk. Sources wait to be processed again."""
    op.execute("UPDATE knowledge_sources SET status = 'pending', error_code = NULL")
    op.drop_index("ix_knowledge_chunks_agent_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_constraint(
        op.f("uq_knowledge_sources_id_agent_id_workspace_id"), "knowledge_sources", type_="unique"
    )
    op.drop_index(
        "uq_jobs_open_subject",
        table_name="jobs",
        postgresql_where="status IN ('queued', 'running')",
    )
    op.drop_index("ix_jobs_status_run_after", table_name="jobs")
    op.drop_table("jobs")
