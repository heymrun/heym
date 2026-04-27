"""add grist credential type

Revision ID: 014
Revises: 013
Create Date: 2026-01-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'grist'")


def downgrade() -> None:
    pass
