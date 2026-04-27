"""Add workflow analytics snapshots table."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_analytics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workflow_name_snapshot",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_executions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "owner_id",
            "bucket_start",
            name="uq_workflow_analytics_snapshot_scope",
        ),
    )
    op.create_index(
        "ix_workflow_analytics_snapshots_workflow_id",
        "workflow_analytics_snapshots",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_analytics_snapshots_owner_id",
        "workflow_analytics_snapshots",
        ["owner_id"],
    )
    op.create_index(
        "ix_workflow_analytics_snapshots_bucket_start",
        "workflow_analytics_snapshots",
        ["bucket_start"],
    )
    op.create_index(
        "ix_workflow_analytics_snapshots_last_run_at",
        "workflow_analytics_snapshots",
        ["last_run_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_analytics_snapshots_last_run_at",
        table_name="workflow_analytics_snapshots",
    )
    op.drop_index(
        "ix_workflow_analytics_snapshots_bucket_start",
        table_name="workflow_analytics_snapshots",
    )
    op.drop_index(
        "ix_workflow_analytics_snapshots_owner_id",
        table_name="workflow_analytics_snapshots",
    )
    op.drop_index(
        "ix_workflow_analytics_snapshots_workflow_id",
        table_name="workflow_analytics_snapshots",
    )
    op.drop_table("workflow_analytics_snapshots")
