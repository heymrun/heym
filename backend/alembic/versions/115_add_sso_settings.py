"""add sso_settings and user SSO identity columns

Revision ID: 115_add_sso_settings
Revises: 114_add_workflow_http_method
Create Date: 2026-08-26 10:00:00.000000

"""

import secrets
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "115_add_sso_settings"
down_revision: Union[str, None] = "114_add_workflow_http_method"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sso_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("issuer", sa.String(512), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("encrypted_client_secret", sa.Text(), nullable=True),
        sa.Column("scopes", sa.String(255), nullable=False, server_default="openid email profile"),
        sa.Column("button_label", sa.String(64), nullable=False, server_default="Sign in with SSO"),
        sa.Column("auto_provision_users", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_email_domains", sa.String(512), nullable=False, server_default=""),
        sa.Column(
            "password_login_disabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_test_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.add_column("users", sa.Column("sso_issuer", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("sso_subject", sa.String(255), nullable=True))
    op.create_index("ix_users_sso_identity", "users", ["sso_issuer", "sso_subject"], unique=True)

    # SSO-provisioned accounts have no password.
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    # NOT NULL cannot be restored while SSO-provisioned rows hold NULL. Give them a valid
    # bcrypt hash of a random secret nobody holds: those accounts simply cannot log in with
    # a password, which is the truthful state. Deleting the users instead would be data loss.
    placeholder = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode()
    op.execute(
        sa.text("UPDATE users SET hashed_password = :h WHERE hashed_password IS NULL").bindparams(
            h=placeholder
        )
    )
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=False)

    op.drop_index("ix_users_sso_identity", table_name="users")
    op.drop_column("users", "sso_subject")
    op.drop_column("users", "sso_issuer")
    op.drop_table("sso_settings")
