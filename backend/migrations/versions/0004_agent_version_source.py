"""the version a rollback was copied from

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24

Additive. Existing versions have no recorded source and none is invented for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FOREIGN_KEY = "fk_agent_versions_agent_id_restored_from_agent_versions"
CHECK = "ck_agent_versions_restored_from_earlier"


def upgrade() -> None:
    op.add_column("agent_versions", sa.Column("restored_from", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f(FOREIGN_KEY),
        "agent_versions",
        "agent_versions",
        ["agent_id", "restored_from"],
        ["agent_id", "number"],
    )
    op.create_check_constraint(op.f(CHECK), "agent_versions", "restored_from < number")


def downgrade() -> None:
    """Loses the recorded sources. The versions themselves stay."""
    op.drop_constraint(op.f(CHECK), "agent_versions", type_="check")
    op.drop_constraint(op.f(FOREIGN_KEY), "agent_versions", type_="foreignkey")
    op.drop_column("agent_versions", "restored_from")
