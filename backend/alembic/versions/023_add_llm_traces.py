"""add llm traces table

Revision ID: 023
Revises: 022
Create Date: 2026-01-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("request_type", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("node_id", sa.String(64), nullable=True),
        sa.Column("node_label", sa.String(255), nullable=True),
        sa.Column(
            "request",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "response",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_traces_user_id", "llm_traces", ["user_id"])
    op.create_index("ix_llm_traces_credential_id", "llm_traces", ["credential_id"])
    op.create_index("ix_llm_traces_workflow_id", "llm_traces", ["workflow_id"])
    op.create_index("ix_llm_traces_created_at", "llm_traces", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_traces_created_at", table_name="llm_traces")
    op.drop_index("ix_llm_traces_workflow_id", table_name="llm_traces")
    op.drop_index("ix_llm_traces_credential_id", table_name="llm_traces")
    op.drop_index("ix_llm_traces_user_id", table_name="llm_traces")
    op.drop_table("llm_traces")
