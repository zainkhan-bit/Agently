"""auth throttle events: counted login and signup attempts

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_throttle_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_throttle_events")),
    )
    op.create_index(
        "ix_auth_throttle_events_lookup",
        "auth_throttle_events",
        ["scope", "key_hash", "created_at"],
    )
    op.create_index("ix_auth_throttle_events_created_at", "auth_throttle_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("auth_throttle_events")
