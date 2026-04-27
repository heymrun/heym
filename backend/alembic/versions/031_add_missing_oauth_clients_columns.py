"""add missing oauth_clients columns (redirect_uris, grant_types, etc.)

Revision ID: 031
Revises: 030
Create Date: 2026-03-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "031"
down_revision: str | None = "030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add all columns that may be missing when table was created with old schema
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS redirect_uris JSONB NOT NULL DEFAULT '[]'
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS grant_types JSONB NOT NULL DEFAULT '["authorization_code"]'
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS response_types JSONB NOT NULL DEFAULT '["code"]'
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS scope VARCHAR(255) NOT NULL DEFAULT 'mcp'
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_clients
        ADD COLUMN IF NOT EXISTS is_confidential BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS redirect_uris")
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS grant_types")
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS response_types")
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS scope")
    op.execute("ALTER TABLE oauth_clients DROP COLUMN IF EXISTS is_confidential")
