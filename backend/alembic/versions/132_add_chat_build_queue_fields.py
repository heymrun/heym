"""add chat build fields to dashboard chat queue items

Revision ID: 132_add_chat_build_queue_fields
Revises: 131_add_work_integration
Create Date: 2026-10-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "132_add_chat_build_queue_fields"
down_revision: Union[str, None] = "131_add_work_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboard_chat_queue_items",
        sa.Column("allow_build", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "dashboard_chat_queue_items",
        sa.Column("build_target_workflow_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dashboard_chat_queue_items", "build_target_workflow_id")
    op.drop_column("dashboard_chat_queue_items", "allow_build")
