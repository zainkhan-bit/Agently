"""executions, and the request a message came with

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-26

Additive. Executions hold no text and are deleted with their conversation (ADR-0005).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_ID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.add_column("messages", sa.Column("request_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_messages_conversation_id_request_id"),
        "messages",
        ["conversation_id", "request_id"],
    )
    op.create_table(
        "executions",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column("message_sequence", sa.Integer(), nullable=False),
        sa.Column("answer_sequence", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("disclosure", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=NEW_ID, nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled', 'timed_out')",
            name=op.f("ck_executions_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (answer_sequence IS NOT NULL)",
            name=op.f("ck_executions_success_has_answer"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_executions_finished_unless_running"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "agent_id"],
            ["conversations.id", "conversations.agent_id"],
            name=op.f("fk_executions_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "agent_version"],
            ["agent_versions.agent_id", "agent_versions.number"],
            name=op.f("fk_executions_agent_id_agent_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "message_sequence"],
            ["messages.conversation_id", "messages.sequence"],
            name=op.f("fk_executions_message"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "answer_sequence"],
            ["messages.conversation_id", "messages.sequence"],
            name=op.f("fk_executions_answer"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_executions")),
    )
    op.create_index("ix_executions_conversation_id", "executions", ["conversation_id"])
    op.create_index(
        "ix_executions_agent_id_agent_version", "executions", ["agent_id", "agent_version"]
    )
    op.create_index(
        "uq_executions_running",
        "executions",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_executions_succeeded",
        "executions",
        ["conversation_id", "message_sequence"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )


def downgrade() -> None:
    """Loses the records of past attempts. Messages stay."""
    op.drop_table("executions")
    op.drop_constraint(op.f("uq_messages_conversation_id_request_id"), "messages", type_="unique")
    op.drop_column("messages", "request_id")
