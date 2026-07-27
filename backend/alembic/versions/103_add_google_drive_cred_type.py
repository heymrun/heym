"""add google drive credential type

Revision ID: 103_add_google_drive_cred_type
Revises: 102_merge_user_ai_live_heads
Create Date: 2026-07-27 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "103_add_google_drive_cred_type"
down_revision: Union[str, None] = "102_merge_user_ai_live_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'google_drive'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; downgrade is a no-op.
    pass
