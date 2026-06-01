"""add jungle grid credential type

Revision ID: 074
Revises: 073
Create Date: 2026-06-01
"""

from alembic import op

revision: str = "074"
down_revision: str | None = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'jungle_grid'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
