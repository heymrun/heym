"""add workflow analysis notes

Revision ID: 081_add_workflow_analysis_notes
Revises: 080_merge_github_supabase_heads
Create Date: 2026-06-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "081_add_workflow_analysis_notes"
down_revision: str | Sequence[str] | None = "080_merge_github_supabase_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_analysis_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_workflow_analysis_notes_workflow_id",
        "workflow_analysis_notes",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_analysis_notes_workflow_id", table_name="workflow_analysis_notes")
    op.drop_table("workflow_analysis_notes")
