"""add the start field values a file run widget sends with its file

Revision ID: 135_add_file_upload_slot_inputs
Revises: 134_add_dashboard_widget_links
Create Date: 2026-10-09 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "135_add_file_upload_slot_inputs"
down_revision: Union[str, None] = "134_add_dashboard_widget_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Set when the slot is minted by a signed-in user; the public upload never sets it.
    op.add_column("file_upload_slots", sa.Column("initial_inputs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("file_upload_slots", "initial_inputs")
