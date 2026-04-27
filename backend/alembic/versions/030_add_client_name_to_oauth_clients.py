"""add client_name column to oauth_clients if missing

Revision ID: 030
Revises: 029
Create Date: 2026-03-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add client_name if missing (table may have been created without it via if_not_exists)
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS client_name VARCHAR(255) NOT NULL DEFAULT 'MCP Client'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS client_name")
