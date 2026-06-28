"""add error_workflow_id and minutes_saved_per_run to workflows

Revision ID: 088_error_wf_time_saved
Revises: 087_add_exec_history_recovered
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "088_error_wf_time_saved"
down_revision: str | None = "087_add_exec_history_recovered"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("error_workflow_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "workflows",
        sa.Column("minutes_saved_per_run", sa.Float(), nullable=True),
    )
    op.create_index("ix_workflows_error_workflow_id", "workflows", ["error_workflow_id"])
    op.create_foreign_key(
        "fk_workflows_error_workflow_id",
        "workflows",
        "workflows",
        ["error_workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_workflows_error_workflow_id", "workflows", type_="foreignkey")
    op.drop_index("ix_workflows_error_workflow_id", table_name="workflows")
    op.drop_column("workflows", "minutes_saved_per_run")
    op.drop_column("workflows", "error_workflow_id")
