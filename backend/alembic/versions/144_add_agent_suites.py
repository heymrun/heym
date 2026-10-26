"""add agent_suites

Revision ID: 144_add_agent_suites
Revises: 143_workflow_concurrency
Create Date: 2026-10-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "144_add_agent_suites"
down_revision: str | Sequence[str] | None = "143_workflow_concurrency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_suites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("node_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("tool_assertions", sa.JSON(), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_suites_owner_id", "agent_suites", ["owner_id"])
    op.create_index("ix_agent_suites_workflow_id", "agent_suites", ["workflow_id"])
    op.create_table(
        "agent_suite_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "suite_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_suites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("generate_inputs", sa.Boolean(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_suite_runs_suite_id", "agent_suite_runs", ["suite_id"])
    # The suite reads an agent's latest traces by workflow and node, newest first.
    op.create_index(
        "ix_llm_traces_workflow_node_created",
        "llm_traces",
        ["workflow_id", "node_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_traces_workflow_node_created", table_name="llm_traces")
    op.drop_index("ix_agent_suite_runs_suite_id", table_name="agent_suite_runs")
    op.drop_table("agent_suite_runs")
    op.drop_index("ix_agent_suites_workflow_id", table_name="agent_suites")
    op.drop_index("ix_agent_suites_owner_id", table_name="agent_suites")
    op.drop_table("agent_suites")
