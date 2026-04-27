"""add workflow versions table

Revision ID: 026
Revises: 025
Create Date: 2026-01-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    workflow_auth_type = postgresql.ENUM(
        "anonymous", "jwt", "header_auth", name="workflow_auth_type", create_type=False
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("nodes", postgresql.JSON(), nullable=False),
        sa.Column("edges", postgresql.JSON(), nullable=False),
        sa.Column("auth_type", workflow_auth_type, nullable=False),
        sa.Column("auth_header_key", sa.String(255), nullable=True),
        sa.Column("auth_header_value", sa.String(1024), nullable=True),
        sa.Column("cache_ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("rate_limit_requests", sa.Integer(), nullable=True),
        sa.Column("rate_limit_window_seconds", sa.Integer(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"])
    op.create_index("ix_workflow_versions_created_at", "workflow_versions", ["created_at"])
    op.create_index(
        "ix_workflow_versions_workflow_version",
        "workflow_versions",
        ["workflow_id", "version_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_versions_workflow_version", table_name="workflow_versions")
    op.drop_index("ix_workflow_versions_created_at", table_name="workflow_versions")
    op.drop_index("ix_workflow_versions_workflow_id", table_name="workflow_versions")
    op.drop_table("workflow_versions")
