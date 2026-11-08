"""Account security: deactivation, session revocation, TOTP two-factor sign-in.

`users.is_active` and `users.sessions_revoked_at` let an administrator end every way an
account authenticates. `users.mfa_secret` holds the authenticator secret encrypted with
ENCRYPTION_KEY, since a TOTP secret must be read back to verify a code and cannot be
hashed. Recovery codes are random and high-entropy, so they are stored as SHA-256
digests in their own table, one row per code, and consumed by deleting the row.

Revision ID: 153_account_security
Revises: 152_encryption_key_rotation
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "153_account_security"
down_revision: str = "152_encryption_key_rotation"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("sessions_revoked_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("mfa_secret", sa.Text()))
    op.add_column("users", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger()))
    op.create_table(
        "user_mfa_recovery_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_user_mfa_recovery_code"),
    )
    op.create_index("ix_user_mfa_recovery_codes_user_id", "user_mfa_recovery_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_mfa_recovery_codes_user_id", table_name="user_mfa_recovery_codes")
    op.drop_table("user_mfa_recovery_codes")
    op.drop_column("users", "mfa_last_step")
    op.drop_column("users", "mfa_enabled_at")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "sessions_revoked_at")
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_active")
