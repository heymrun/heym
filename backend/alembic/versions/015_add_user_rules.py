"""add user_rules column to users table

Revision ID: 015
Revises: 014
Create Date: 2026-01-11

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("user_rules", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "user_rules")
