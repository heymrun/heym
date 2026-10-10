"""let a queued chat turn write an agent skill without build mode

Revision ID: 136_add_chat_skill_write
Revises: 135_add_file_upload_slot_inputs
Create Date: 2026-10-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "136_add_chat_skill_write"
down_revision: Union[str, None] = "135_add_file_upload_slot_inputs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboard_chat_queue_items",
        sa.Column("allow_skill_write", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("dashboard_chat_queue_items", "allow_skill_write")
