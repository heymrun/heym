"""persist active running-node start timestamps for live timelines

Revision ID: 121_running_node_start_times
Revises: 120_queue_chart_return
Create Date: 2026-08-29 20:34:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "121_running_node_start_times"
down_revision: Union[str, None] = "120_queue_chart_return"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "active_workflow_executions",
        sa.Column(
            "running_node_started_at_ms",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("active_workflow_executions", "running_node_started_at_ms")
