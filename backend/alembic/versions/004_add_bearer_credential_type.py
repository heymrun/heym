"""add bearer credential type

Revision ID: 004
Revises: 003
Create Date: 2026-01-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'bearer'")


def downgrade() -> None:
    pass
