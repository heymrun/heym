"""add used column to oauth_authorization_codes

Revision ID: 034
Revises: 033
Create Date: 2026-03-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE oauth_authorization_codes
        ADD COLUMN IF NOT EXISTS used BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE oauth_authorization_codes DROP COLUMN IF EXISTS used")
