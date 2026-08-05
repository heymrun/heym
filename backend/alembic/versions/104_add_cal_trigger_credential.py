"""Preserve the original Cal.com trigger revision for upgrade compatibility.

Revision ID: 104_add_cal_trigger_credential
Revises: 103_add_google_drive_cred_type
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "104_add_cal_trigger_credential"
down_revision: str | None = "103_add_google_drive_cred_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the credential value created by the original revision."""
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cal_trigger'")


def downgrade() -> None:
    """Leave the PostgreSQL enum value in place because removing it is unsafe."""
