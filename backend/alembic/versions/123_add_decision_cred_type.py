"""add decision credential type

Revision ID: 123_add_decision_cred_type
Revises: 122_vsi_metadata_index
Create Date: 2026-09-21 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "123_add_decision_cred_type"
down_revision: Union[str, None] = "122_vsi_metadata_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'decision'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
