"""Bind MCP sessions to API key generations.

Revision ID: 163_mcp_api_key_version
Revises: 162_run_history_started_by
Create Date: 2026-11-27
"""

import secrets

import sqlalchemy as sa

from alembic import op

revision = "163_mcp_api_key_version"
down_revision = "162_run_history_started_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mcp_api_key_version", sa.String(36), nullable=True))
    op.add_column("mcp_servers", sa.Column("api_key_version", sa.String(36), nullable=True))

    conn = op.get_bind()
    user_rows = conn.execute(
        sa.text("SELECT id FROM users WHERE mcp_api_key IS NOT NULL")
    ).fetchall()
    for (user_id,) in user_rows:
        conn.execute(
            sa.text("UPDATE users SET mcp_api_key_version = :version WHERE id = :user_id"),
            {"version": secrets.token_hex(16), "user_id": user_id},
        )

    server_rows = conn.execute(
        sa.text("SELECT id FROM mcp_servers WHERE api_key IS NOT NULL")
    ).fetchall()
    for (server_id,) in server_rows:
        conn.execute(
            sa.text("UPDATE mcp_servers SET api_key_version = :version WHERE id = :server_id"),
            {"version": secrets.token_hex(16), "server_id": server_id},
        )


def downgrade() -> None:
    op.drop_column("mcp_servers", "api_key_version")
    op.drop_column("users", "mcp_api_key_version")
