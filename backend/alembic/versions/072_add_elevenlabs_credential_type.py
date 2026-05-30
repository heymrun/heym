"""add elevenlabs credential type

Revision ID: 072
Revises: 071
Create Date: 2026-05-30
"""

from alembic import op

revision: str = "072"
down_revision: str | None = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'elevenlabs'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
