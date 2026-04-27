"""Add trigger_source to execution_history

Revision ID: 019
Revises: 018
Create Date: 2026-01-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_history",
        sa.Column("trigger_source", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_history", "trigger_source")
