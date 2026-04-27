"""add redis credential type

Revision ID: 011
Revises: 010
Create Date: 2026-01-09

"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'redis'")


def downgrade() -> None:
    pass
