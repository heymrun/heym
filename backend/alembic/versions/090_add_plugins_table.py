"""add plugins table

Revision ID: 090_add_plugins_table
Revises: 089_workflow_timeout
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "090_add_plugins_table"
down_revision: str | None = "089_workflow_timeout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plugin_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
    )
    op.create_index("ix_plugins_plugin_id", "plugins", ["plugin_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_plugins_plugin_id", table_name="plugins")
    op.drop_table("plugins")
