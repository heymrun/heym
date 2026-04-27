"""add telegram credential type

Revision ID: 059_add_telegram_credential_type
Revises: 058
Create Date: 2026-04-20 18:30:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "059_add_telegram_credential_type"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'telegram'")


def downgrade() -> None:
    pass
