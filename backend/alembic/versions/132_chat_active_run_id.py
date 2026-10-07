"""add active_run_id to dashboard_conversations

Revision ID: 132_chat_active_run_id
Revises: 131_add_work_integration
Create Date: 2026-10-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "132_chat_active_run_id"
down_revision: Union[str, None] = "131_add_work_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboard_conversations",
        sa.Column(
            "active_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("dashboard_conversations", "active_run_id")
