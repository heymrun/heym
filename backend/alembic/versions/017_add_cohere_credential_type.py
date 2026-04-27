"""add cohere credential type

Revision ID: 017
Revises: 016
Create Date: 2026-01-12

"""

from collections.abc import Sequence

from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cohere'")


def downgrade() -> None:
    pass
