"""add slack_trigger credential type

Revision ID: 056
Revises: 055
Create Date: 2026-04-16
"""

from alembic import op

revision: str = "056"
down_revision: str = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'slack_trigger'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
