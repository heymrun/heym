"""add slack credential type

Revision ID: 006
Revises: 005
Create Date: 2026-01-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'slack'")


def downgrade() -> None:
    pass
