"""node analytics: hourly per-node-type rollups and the execution_history marker

Revision ID: 148_node_analytics
Revises: 147_a2a_agent
Create Date: 2026-10-28 00:00:00.000000

Existing runs are never rolled up. The marker is added with a fast default of false, so
existing rows read false without a table rewrite, and only then does its default become
true for the rows written from now on. Downgrade drops the rollups; they cannot be rebuilt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "148_node_analytics"
down_revision: str | Sequence[str] | None = "147_a2a_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_history",
        sa.Column(
            "node_analytics_pending", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("execution_history", "node_analytics_pending", server_default=sa.true())
    op.create_table(
        "node_analytics_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_type", sa.String(100), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "workflow_id", "node_type", "bucket_start", name="uq_node_analytics_snapshot_scope"
        ),
    )
    op.create_index(
        "ix_node_analytics_snapshots_bucket_start", "node_analytics_snapshots", ["bucket_start"]
    )
    # execution_history can be large: build without blocking writes. The index only ever
    # holds runs the rollup has not counted yet.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_execution_history_node_analytics_pending",
            "execution_history",
            ["started_at"],
            postgresql_where=sa.text("node_analytics_pending"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    op.drop_index("ix_execution_history_node_analytics_pending", table_name="execution_history")
    op.drop_index("ix_node_analytics_snapshots_bucket_start", table_name="node_analytics_snapshots")
    op.drop_table("node_analytics_snapshots")
    op.drop_column("execution_history", "node_analytics_pending")
