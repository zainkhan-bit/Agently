"""private conversations and their messages

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-26

Additive. Deleting an agent or a membership deletes its conversations (ADR-0005).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")
NEW_ID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_agents_id_workspace_id"), "agents", ["id", "workspace_id"])
    op.create_table(
        "conversations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=NEW_ID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "message_count >= 0", name=op.f("ck_conversations_message_count_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "workspace_id"],
            ["agents.id", "agents.workspace_id"],
            name=op.f("fk_conversations_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["memberships.user_id", "memberships.workspace_id"],
            name=op.f("fk_conversations_user_id_memberships"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("id", "agent_id", name=op.f("uq_conversations_id_agent_id")),
    )
    op.create_index(
        "ix_conversations_agent_id_user_id_updated_at",
        "conversations",
        ["agent_id", "user_id", "updated_at"],
    )
    op.create_index(
        "ix_conversations_user_id_workspace_id", "conversations", ["user_id", "workspace_id"]
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=NEW_ID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_messages_sequence_positive")),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_messages_role_valid")),
        sa.CheckConstraint(
            "(role = 'assistant') = (agent_version IS NOT NULL)",
            name=op.f("ck_messages_version_of_assistant"),
        ),
        sa.CheckConstraint("content <> ''", name=op.f("ck_messages_content_not_empty")),
        sa.ForeignKeyConstraint(
            ["conversation_id", "agent_id"],
            ["conversations.id", "conversations.agent_id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "agent_version"],
            ["agent_versions.agent_id", "agent_versions.number"],
            name=op.f("fk_messages_agent_id_agent_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name=op.f("uq_messages_conversation_id_sequence")
        ),
    )
    op.create_index("ix_messages_agent_id_agent_version", "messages", ["agent_id", "agent_version"])


def downgrade() -> None:
    """Deletes every conversation."""
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_constraint(op.f("uq_agents_id_workspace_id"), "agents", type_="unique")
