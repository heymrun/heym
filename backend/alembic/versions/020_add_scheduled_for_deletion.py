"""add scheduled_for_deletion to workflows

Revision ID: 020
Revises: 019
Create Date: 2026-01-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("scheduled_for_deletion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_workflows_scheduled_for_deletion",
        "workflows",
        ["scheduled_for_deletion"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workflows_scheduled_for_deletion", table_name="workflows")
    op.drop_column("workflows", "scheduled_for_deletion")
