"""add google_sheets credential type

Revision ID: 055
Revises: 054
Create Date: 2026-04-15
"""

from alembic import op

revision: str = "055"
down_revision: str = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'google_sheets'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
