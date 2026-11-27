"""knowledge sources

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-27

Additive. Records hold no file content; files live in private storage under random names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_name", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
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
            "kind IN ('pdf', 'docx', 'txt', 'md')", name=op.f("ck_knowledge_sources_kind_valid")
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_knowledge_sources_sha256_hex")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name=op.f("ck_knowledge_sources_status_valid"),
        ),
        sa.CheckConstraint(
            "storage_name ~ '^[0-9a-f]{32}$'", name=op.f("ck_knowledge_sources_storage_name_random")
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_knowledge_sources_size_positive")),
        sa.ForeignKeyConstraint(
            ["agent_id", "workspace_id"],
            ["agents.id", "agents.workspace_id"],
            name=op.f("fk_knowledge_sources_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_knowledge_sources_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_sources")),
    )
    op.create_index(
        "ix_knowledge_sources_agent_id_created_at",
        "knowledge_sources",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_sources_workspace_id", "knowledge_sources", ["workspace_id"], unique=False
    )
    op.create_index(
        "uq_knowledge_sources_agent_id_sha256",
        "knowledge_sources",
        ["agent_id", "sha256"],
        unique=True,
    )
    op.create_index(
        "uq_knowledge_sources_storage_name", "knowledge_sources", ["storage_name"], unique=True
    )


def downgrade() -> None:
    """Deletes every source record. The files stay in storage until the sweep removes them."""
    op.drop_index("uq_knowledge_sources_storage_name", table_name="knowledge_sources")
    op.drop_index("uq_knowledge_sources_agent_id_sha256", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_workspace_id", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_agent_id_created_at", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
