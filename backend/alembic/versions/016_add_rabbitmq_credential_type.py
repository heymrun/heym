"""add rabbitmq credential type

Revision ID: 016
Revises: 015
Create Date: 2026-01-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'rabbitmq'")


def downgrade() -> None:
    pass
