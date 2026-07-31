"""add Cal.com Trigger credential type

Revision ID: 104_add_cal_trigger_credential
Revises: 103_add_google_drive_cred_type
Create Date: 2026-07-31 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "104_add_cal_trigger_credential"
down_revision: Union[str, None] = "103_add_google_drive_cred_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cal_trigger'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value safely; downgrade is a no-op.
    pass
