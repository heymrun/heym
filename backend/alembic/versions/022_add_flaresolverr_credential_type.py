"""add flaresolverr credential type

Revision ID: 022
Revises: 021
Create Date: 2026-01-13

"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'flaresolverr'")


def downgrade() -> None:
    pass
