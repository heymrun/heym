"""add missing oauth_authorization_codes columns (scope, code_challenge, etc.)

Revision ID: 033
Revises: 032
Create Date: 2026-03-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "033"
down_revision: str | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE oauth_authorization_codes
        ADD COLUMN IF NOT EXISTS scope VARCHAR(255) NOT NULL DEFAULT 'mcp'
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_authorization_codes
        ADD COLUMN IF NOT EXISTS code_challenge VARCHAR(128) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_authorization_codes
        ADD COLUMN IF NOT EXISTS code_challenge_method VARCHAR(10) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_authorization_codes
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        """
        ALTER TABLE oauth_authorization_codes
        ADD COLUMN IF NOT EXISTS used BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE oauth_authorization_codes DROP COLUMN IF EXISTS scope")
    op.execute("ALTER TABLE oauth_authorization_codes DROP COLUMN IF EXISTS code_challenge")
    op.execute("ALTER TABLE oauth_authorization_codes DROP COLUMN IF EXISTS code_challenge_method")
    op.execute("ALTER TABLE oauth_authorization_codes DROP COLUMN IF EXISTS created_at")
