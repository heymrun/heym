"""add OAuth 2.1 tables for MCP connector authentication

Revision ID: 029
Revises: 028
Create Date: 2026-03-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("client_secret_hash", sa.String(255), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("redirect_uris", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "grant_types",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default='["authorization_code"]',
        ),
        sa.Column(
            "response_types",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default='["code"]',
        ),
        sa.Column("scope", sa.String(255), nullable=False, server_default="mcp"),
        sa.Column("is_confidential", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_oauth_clients_client_id",
        "oauth_clients",
        ["client_id"],
        unique=True,
        if_not_exists=True,
    )

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=True),
        sa.Column("code_challenge_method", sa.String(10), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_oauth_auth_codes_code",
        "oauth_authorization_codes",
        ["code"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_oauth_auth_codes_expires_at",
        "oauth_authorization_codes",
        ["expires_at"],
        if_not_exists=True,
    )

    op.create_table(
        "oauth_access_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_token", sa.String(255), nullable=False),
        sa.Column("refresh_token", sa.String(255), nullable=True),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_oauth_access_tokens_token",
        "oauth_access_tokens",
        ["access_token"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_oauth_access_tokens_refresh",
        "oauth_access_tokens",
        ["refresh_token"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_oauth_access_tokens_expires",
        "oauth_access_tokens",
        ["expires_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("oauth_access_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
