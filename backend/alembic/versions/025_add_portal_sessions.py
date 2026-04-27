"""add portal sessions table

Revision ID: 025
Revises: 024
Create Date: 2026-01-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(255), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_sessions_token", "portal_sessions", ["token"], unique=True)
    op.create_index("ix_portal_sessions_expires_at", "portal_sessions", ["expires_at"])
    op.create_index("ix_portal_sessions_workflow_id", "portal_sessions", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_portal_sessions_workflow_id", table_name="portal_sessions")
    op.drop_index("ix_portal_sessions_expires_at", table_name="portal_sessions")
    op.drop_index("ix_portal_sessions_token", table_name="portal_sessions")
    op.drop_table("portal_sessions")
