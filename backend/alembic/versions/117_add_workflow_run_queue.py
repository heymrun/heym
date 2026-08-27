"""add workflow_run_queue and cluster_dispatch_state

Revision ID: 117_add_workflow_run_queue
Revises: 116_add_cluster_instances
Create Date: 2026-08-27 10:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "117_add_workflow_run_queue"
down_revision: Union[str, None] = "116_add_cluster_instances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("placement", sa.String(16), nullable=False),
        sa.Column("target_instance_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trigger_source", sa.String(50), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credentials_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("test_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timeout_seconds", sa.Float(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_process", sa.String(128), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_workflow_run_queue_claim",
        "workflow_run_queue",
        ["target_instance_id", "status", "enqueued_at"],
    )
    op.create_index("ix_workflow_run_queue_status", "workflow_run_queue", ["status"])

    op.create_table(
        "cluster_dispatch_state",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("counters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute("INSERT INTO cluster_dispatch_state (id, counters) VALUES ('singleton', '{}')")


def downgrade() -> None:
    op.drop_table("cluster_dispatch_state")
    op.drop_index("ix_workflow_run_queue_status", table_name="workflow_run_queue")
    op.drop_index("ix_workflow_run_queue_claim", table_name="workflow_run_queue")
    op.drop_table("workflow_run_queue")
