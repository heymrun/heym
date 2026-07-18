"""add opencode credential type

Revision ID: 100_add_opencode_credential_type
Revises: 099_add_board_shares
Create Date: 2026-07-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "100_add_opencode_credential_type"
down_revision: Union[str, None] = "099_add_board_shares"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'opencode'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; downgrade is a no-op.
    pass
