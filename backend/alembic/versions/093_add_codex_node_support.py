"""add Codex credential and follow-up requests

Revision ID: 093_add_codex_node_support
Revises: 092_add_sentry_credential_type
Create Date: 2026-07-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "093_add_codex_node_support"
down_revision: Union[str, None] = "092_add_sentry_credential_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'codex'")
    op.create_table(
        "codex_followup_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_history_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_token", sa.String(length=255), nullable=False),
        sa.Column("workflow_name", sa.String(length=255), nullable=False),
        sa.Column("codex_node_id", sa.String(length=64), nullable=False),
        sa.Column("codex_label", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("task_prompt", sa.Text(), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("workspace_path", sa.Text(), nullable=True),
        sa.Column("original_output", postgresql.JSON(), nullable=False),
        sa.Column("resolved_output", postgresql.JSON(), nullable=False),
        sa.Column("execution_snapshot", postgresql.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("resume_error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["execution_history_id"],
            ["execution_history.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_token"),
    )
    op.create_index(
        "ix_codex_followup_requests_codex_node_id",
        "codex_followup_requests",
        ["codex_node_id"],
    )
    op.create_index(
        "ix_codex_followup_requests_execution_history_id",
        "codex_followup_requests",
        ["execution_history_id"],
    )
    op.create_index(
        "ix_codex_followup_requests_expires_at",
        "codex_followup_requests",
        ["expires_at"],
    )
    op.create_index(
        "ix_codex_followup_requests_public_token",
        "codex_followup_requests",
        ["public_token"],
        unique=True,
    )
    op.create_index(
        "ix_codex_followup_requests_status",
        "codex_followup_requests",
        ["status"],
    )
    op.create_index(
        "ix_codex_followup_requests_workflow_id",
        "codex_followup_requests",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_codex_followup_requests_workflow_id", table_name="codex_followup_requests")
    op.drop_index("ix_codex_followup_requests_status", table_name="codex_followup_requests")
    op.drop_index("ix_codex_followup_requests_public_token", table_name="codex_followup_requests")
    op.drop_index("ix_codex_followup_requests_expires_at", table_name="codex_followup_requests")
    op.drop_index(
        "ix_codex_followup_requests_execution_history_id",
        table_name="codex_followup_requests",
    )
    op.drop_index(
        "ix_codex_followup_requests_codex_node_id",
        table_name="codex_followup_requests",
    )
    op.drop_table("codex_followup_requests")
