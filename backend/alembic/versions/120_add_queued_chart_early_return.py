"""preserve chart early-return behavior for offloaded dashboard runs

Revision ID: 120_queue_chart_return
Revises: 119_add_auto_weighting
Create Date: 2026-08-29 17:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "120_queue_chart_return"
down_revision: Union[str, None] = "119_add_auto_weighting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_run_queue",
        sa.Column(
            "return_on_chart_output", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_run_queue", "return_on_chart_output")
