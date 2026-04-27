"""Add user_workflow_folders and mcp_enabled to workflow_shares

Revision ID: 021_add_user_workflow_settings
Revises: 020_add_scheduled_for_deletion
Create Date: 2026-01-13

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_shares",
        sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "workflow_shares",
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_workflow_shares_folder_id", "workflow_shares", ["folder_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_workflow_shares_folder_id", table_name="workflow_shares")
    op.drop_column("workflow_shares", "folder_id")
    op.drop_column("workflow_shares", "mcp_enabled")
