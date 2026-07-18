"""Add cross-worker live execution snapshots.

Revision ID: 102_add_live_execution_snapshots
Revises: 101_add_user_ai_defaults
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "102_add_live_execution_snapshots"
down_revision: str | None = "101_add_user_ai_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "active_workflow_executions",
        sa.Column("running_node_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("node_results", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "board_card_runs",
        sa.Column("active_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_board_card_runs_active_execution_id",
        "board_card_runs",
        ["active_execution_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_board_card_runs_active_execution_id", table_name="board_card_runs")
    op.drop_column("board_card_runs", "active_execution_id")
    op.drop_column("active_workflow_executions", "node_results")
    op.drop_column("active_workflow_executions", "running_node_ids")
