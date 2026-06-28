"""add run crash-recovery fields

Revision ID: 086_add_run_recovery_fields
Revises: 085_backfill_linear_cred_type
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "086_add_run_recovery_fields"
down_revision: str | None = "085_backfill_linear_cred_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "active_workflow_executions",
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("trigger_source", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("recoverable", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_active_workflow_executions_recoverable",
        "active_workflow_executions",
        ["recoverable"],
    )
    op.add_column(
        "workflows",
        sa.Column("auto_recover_runs", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("workflows", "auto_recover_runs")
    op.drop_index(
        "ix_active_workflow_executions_recoverable",
        table_name="active_workflow_executions",
    )
    op.drop_column("active_workflow_executions", "recoverable")
    op.drop_column("active_workflow_executions", "attempt")
    op.drop_column("active_workflow_executions", "actor_user_id")
    op.drop_column("active_workflow_executions", "trigger_source")
    op.drop_column("active_workflow_executions", "inputs")
