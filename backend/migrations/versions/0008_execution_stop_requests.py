"""a request to stop an execution

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-27

Additive. A stop is recorded as a request; the run settles the execution once its call ended.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "executions", sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("executions", "stop_requested_at")
