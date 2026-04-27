"""Add sse_enabled and sse_node_config columns to workflows."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "054"
down_revision: str | None = "053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("sse_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "workflows",
        sa.Column("sse_node_config", postgresql.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflows", "sse_node_config")
    op.drop_column("workflows", "sse_enabled")
