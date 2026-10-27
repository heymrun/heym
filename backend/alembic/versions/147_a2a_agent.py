"""a2a agent: A2A switches, tasks, and task history on chat messages

Revision ID: 147_a2a_agent
Revises: 146_eval_run_runs_per_test
Create Date: 2026-10-27 00:00:00.000000

Every switch starts off and nothing is backfilled. No secret is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "147_a2a_agent"
down_revision: str | Sequence[str] | None = "146_eval_run_runs_per_test"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mcp_a2a_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("a2a_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "a2a_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mcp_server_id",
            UUID(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "context_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dashboard_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("artifacts", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_a2a_tasks_user_id", "a2a_tasks", ["user_id"])
    op.create_index("ix_a2a_tasks_context_id", "a2a_tasks", ["context_id"])
    op.create_index(
        "ix_a2a_tasks_user_server_updated",
        "a2a_tasks",
        ["user_id", "mcp_server_id", "updated_at"],
    )
    op.add_column(
        "dashboard_messages",
        sa.Column(
            "a2a_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("a2a_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_dashboard_messages_a2a_task_id", "dashboard_messages", ["a2a_task_id"])


def downgrade() -> None:
    op.drop_index("ix_dashboard_messages_a2a_task_id", table_name="dashboard_messages")
    op.drop_column("dashboard_messages", "a2a_task_id")
    op.drop_index("ix_a2a_tasks_user_server_updated", table_name="a2a_tasks")
    op.drop_index("ix_a2a_tasks_context_id", table_name="a2a_tasks")
    op.drop_index("ix_a2a_tasks_user_id", table_name="a2a_tasks")
    op.drop_table("a2a_tasks")
    op.drop_column("mcp_servers", "a2a_enabled")
    op.drop_column("users", "mcp_a2a_enabled")
