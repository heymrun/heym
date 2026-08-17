"""add folder icon

Revision ID: 112_add_folder_icon
Revises: 111_backfill_oauth_token_hashes
Create Date: 2026-08-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "112_add_folder_icon"
down_revision: str | None = "111_backfill_oauth_token_hashes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("folders", sa.Column("icon", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("folders", "icon")
