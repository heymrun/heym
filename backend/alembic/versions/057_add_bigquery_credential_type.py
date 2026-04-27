"""add bigquery credential type

Revision ID: 057
Revises: 056
Create Date: 2026-04-16
"""

from alembic import op

revision: str = "057"
down_revision: str = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'bigquery'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
