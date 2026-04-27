"""add imap credential type

Revision ID: 058
Revises: 057
Create Date: 2026-04-20
"""

from alembic import op

revision: str = "058"
down_revision: str = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'imap'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
