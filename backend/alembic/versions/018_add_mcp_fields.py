"""add mcp_api_key to users and mcp_enabled to workflows

Revision ID: 018
Revises: 017
Create Date: 2026-01-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mcp_api_key", sa.String(64), nullable=True))
    op.create_index("ix_users_mcp_api_key", "users", ["mcp_api_key"], unique=True)
    op.add_column(
        "workflows", sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default="false")
    )


def downgrade() -> None:
    op.drop_column("workflows", "mcp_enabled")
    op.drop_index("ix_users_mcp_api_key", table_name="users")
    op.drop_column("users", "mcp_api_key")
