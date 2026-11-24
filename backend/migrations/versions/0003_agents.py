"""agents and their immutable configuration versions

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24

Deleting a workspace deletes its agents; deleting an agent deletes its versions (ADR-0005).
Deleting a user keeps both and empties created_by.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _timestamp(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "agents",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _timestamp("updated_at"),
        _timestamp("created_at"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived')", name=op.f("ck_agents_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_agents_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    op.create_index("ix_agents_workspace_id_created_at", "agents", ["workspace_id", "created_at"])
    op.create_index(op.f("ix_agents_created_by"), "agents", ["created_by"])

    op.create_table(
        "agent_versions",
        _id(),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=True),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        sa.CheckConstraint("number >= 1", name=op.f("ck_agent_versions_number_positive")),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_versions_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_agent_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint("agent_id", "number", name=op.f("uq_agent_versions_agent_id_number")),
    )
    op.create_index(op.f("ix_agent_versions_created_by"), "agent_versions", ["created_by"])


def downgrade() -> None:
    op.drop_table("agent_versions")
    op.drop_table("agents")
