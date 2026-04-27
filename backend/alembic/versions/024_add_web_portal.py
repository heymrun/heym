"""add web portal fields and portal users table

Revision ID: 024
Revises: 023
Create Date: 2026-01-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("portal_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "workflows",
        sa.Column("portal_slug", sa.String(255), nullable=True, unique=True),
    )
    op.add_column(
        "workflows",
        sa.Column("portal_stream_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "portal_file_upload_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "portal_file_config",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    op.create_index("ix_workflows_portal_slug", "workflows", ["portal_slug"], unique=True)

    op.create_table(
        "workflow_portal_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "username", name="uq_portal_user_workflow_username"),
    )
    op.create_index(
        "ix_workflow_portal_users_workflow_id", "workflow_portal_users", ["workflow_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_portal_users_workflow_id", table_name="workflow_portal_users")
    op.drop_table("workflow_portal_users")
    op.drop_index("ix_workflows_portal_slug", table_name="workflows")
    op.drop_column("workflows", "portal_file_config")
    op.drop_column("workflows", "portal_file_upload_enabled")
    op.drop_column("workflows", "portal_stream_enabled")
    op.drop_column("workflows", "portal_slug")
    op.drop_column("workflows", "portal_enabled")
