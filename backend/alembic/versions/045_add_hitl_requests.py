"""Add HITL requests table."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "hitl_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "execution_history_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_token", sa.String(length=255), nullable=False),
        sa.Column("workflow_name", sa.String(length=255), nullable=False),
        sa.Column("agent_node_id", sa.String(length=64), nullable=False),
        sa.Column("agent_label", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("original_draft_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("original_agent_output", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved_output", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("resume_error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_hitl_requests_workflow_id", "hitl_requests", ["workflow_id"])
    op.create_index(
        "ix_hitl_requests_execution_history_id",
        "hitl_requests",
        ["execution_history_id"],
    )
    op.create_index("ix_hitl_requests_public_token", "hitl_requests", ["public_token"], unique=True)
    op.create_index("ix_hitl_requests_agent_node_id", "hitl_requests", ["agent_node_id"])
    op.create_index("ix_hitl_requests_status", "hitl_requests", ["status"])
    op.create_index("ix_hitl_requests_expires_at", "hitl_requests", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_hitl_requests_expires_at", table_name="hitl_requests")
    op.drop_index("ix_hitl_requests_status", table_name="hitl_requests")
    op.drop_index("ix_hitl_requests_agent_node_id", table_name="hitl_requests")
    op.drop_index("ix_hitl_requests_public_token", table_name="hitl_requests")
    op.drop_index("ix_hitl_requests_execution_history_id", table_name="hitl_requests")
    op.drop_index("ix_hitl_requests_workflow_id", table_name="hitl_requests")
    op.drop_table("hitl_requests")
