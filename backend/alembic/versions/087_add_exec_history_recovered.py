"""add recovered flag to execution history

Revision ID: 087_add_exec_history_recovered
Revises: 086_add_run_recovery_fields
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "087_add_exec_history_recovered"
down_revision: str | None = "086_add_run_recovery_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_history",
        sa.Column("recovered", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("execution_history", "recovered")
