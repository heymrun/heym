"""add executing-instance attribution to execution history

Revision ID: 118_add_run_instance_attr
Revises: 117_add_workflow_run_queue
Create Date: 2026-08-27 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "118_add_run_instance_attr"
down_revision: Union[str, None] = "117_add_workflow_run_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("execution_history", "active_workflow_executions")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("executed_by_instance_id", sa.String(128), nullable=True))
        op.add_column(table, sa.Column("executed_by_instance_name", sa.String(128), nullable=True))
    # execution_history grows without bound and the history dialog filters on it.
    # active_workflow_executions holds only in-flight runs and stays unindexed.
    op.create_index(
        "ix_execution_history_executed_by_instance_id",
        "execution_history",
        ["executed_by_instance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_history_executed_by_instance_id", table_name="execution_history")
    for table in _TABLES:
        op.drop_column(table, "executed_by_instance_name")
        op.drop_column(table, "executed_by_instance_id")
