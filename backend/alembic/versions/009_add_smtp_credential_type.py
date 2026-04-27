"""add smtp credential type

Revision ID: 009
Revises: 008
Create Date: 2026-01-07

"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'smtp'")


def downgrade() -> None:
    pass
