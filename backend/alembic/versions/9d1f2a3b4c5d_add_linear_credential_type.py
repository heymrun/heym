"""add linear credential type

Revision ID: 9d1f2a3b4c5d
Revises: 9cbd3c82d23b
Create Date: 2026-06-23 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9d1f2a3b4c5d"
down_revision: str | Sequence[str] | None = "9cbd3c82d23b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'linear'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without rebuilding the type.
    pass
