"""Persist endpoint_path for named MCP servers; backfill existing with sse, default new to mcp.

Revision ID: 155_mcp_server_endpoint_path
Revises: 154_vector_store_ingest_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "155_mcp_server_endpoint_path"
down_revision: str | Sequence[str] | None = "154_vector_store_ingest_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add column with server_default='sse' so all existing rows are backfilled with 'sse'
    op.add_column(
        "mcp_servers",
        sa.Column("endpoint_path", sa.String(length=16), nullable=False, server_default="sse"),
    )
    # Update default to 'mcp' for subsequent newly created records
    op.alter_column(
        "mcp_servers",
        "endpoint_path",
        server_default="mcp",
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "endpoint_path")
