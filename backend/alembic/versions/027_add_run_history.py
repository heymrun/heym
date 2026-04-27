"""add run_history table for chat run history

Revision ID: 027
Revises: 026
Create Date: 2026-02-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_type", sa.String(50), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_source", sa.String(50), nullable=True),
        sa.Column(
            "inputs",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "outputs",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("execution_time_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_run_history_user_id", "run_history", ["user_id"])
    op.create_index("ix_run_history_run_type", "run_history", ["run_type"])
    op.create_index("ix_run_history_workflow_id", "run_history", ["workflow_id"])
    op.create_index("ix_run_history_started_at", "run_history", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_run_history_started_at", table_name="run_history")
    op.drop_index("ix_run_history_workflow_id", table_name="run_history")
    op.drop_index("ix_run_history_run_type", table_name="run_history")
    op.drop_index("ix_run_history_user_id", table_name="run_history")
    op.drop_table("run_history")
