"""Persist endpoint_path for named MCP servers; backfill existing with sse, default new to mcp.

Revision ID: 155_mcp_server_endpoint_path
Revises: 154_vector_store_ingest_jobs
"""

from collections.abc import Sequence

from alembic import op

revision: str = "155_mcp_server_endpoint_path"
down_revision: str | Sequence[str] | None = "154_vector_store_ingest_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A database stamped back to 154 after running this revision (a rollback, or a branch
    # without it) already has the column. Rows that existed when it was added keep 'sse'.
    op.execute(
        "ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS endpoint_path VARCHAR(16) "
        "NOT NULL DEFAULT 'sse'"
    )
    op.execute("ALTER TABLE mcp_servers ALTER COLUMN endpoint_path SET DEFAULT 'mcp'")


def downgrade() -> None:
    op.execute("ALTER TABLE mcp_servers DROP COLUMN IF EXISTS endpoint_path")
