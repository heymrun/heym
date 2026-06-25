"""add updated_at to mcp_servers

Revision ID: 083_add_mcp_server_updated_at
Revises: 082_merge_notion_pgvector_heads
Create Date: 2026-06-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "083_add_mcp_server_updated_at"
down_revision: str | Sequence[str] | None = "082_merge_notion_pgvector_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("UPDATE mcp_servers SET updated_at = created_at")
    op.create_index("ix_mcp_servers_updated_at", "mcp_servers", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_updated_at", table_name="mcp_servers")
    op.drop_column("mcp_servers", "updated_at")
