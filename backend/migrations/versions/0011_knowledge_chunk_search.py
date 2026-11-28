"""knowledge chunk search columns

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-28

Additive. Two search forms of each chunk's text, generated and stored by PostgreSQL, with GIN
indexes. Adding a stored generated column rewrites knowledge_chunks once and fills the columns for
chunks that already exist; chunk text itself is not changed. See ADR-0007.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = {
    "search_english": "to_tsvector('english'::regconfig, content)",
    "search_simple": "to_tsvector('simple'::regconfig, content)",
}


def upgrade() -> None:
    for name, expression in COLUMNS.items():
        op.add_column(
            "knowledge_chunks",
            sa.Column(
                name,
                postgresql.TSVECTOR(),
                sa.Computed(expression, persisted=True),
                nullable=True,
            ),
        )
        op.create_index(
            f"ix_knowledge_chunks_{name}", "knowledge_chunks", [name], postgresql_using="gin"
        )


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_index(f"ix_knowledge_chunks_{name}", table_name="knowledge_chunks")
        op.drop_column("knowledge_chunks", name)
