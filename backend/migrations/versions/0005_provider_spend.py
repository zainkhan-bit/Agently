"""what real provider calls cost

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25

Additive. No prompt, answer, person or workspace is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_spend",
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("cost_nano_usd", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("cost_nano_usd >= 0", name=op.f("ck_provider_spend_cost_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_spend")),
    )
    op.create_index("ix_provider_spend_created_at", "provider_spend", ["created_at"])


def downgrade() -> None:
    """Forgets what was spent, so the limits start again from zero."""
    op.drop_index("ix_provider_spend_created_at", table_name="provider_spend")
    op.drop_table("provider_spend")
