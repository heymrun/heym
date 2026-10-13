"""Carry W3C trace context across the workflow run queue.

Revision ID: 138_add_queue_trace_context
Revises: 137_add_smtp_from_key
Create Date: 2026-10-14 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "138_add_queue_trace_context"
down_revision: Union[str, None] = "137_add_smtp_from_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_run_queue",
        sa.Column("trace_context", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_run_queue", "trace_context")
