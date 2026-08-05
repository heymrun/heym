"""add rag credential type

Revision ID: 105_add_rag_credential_type
Revises: 104_add_cron_slot_claims
Create Date: 2026-08-05 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "105_add_rag_credential_type"
down_revision: Union[str, None] = "104_add_cron_slot_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'rag'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
