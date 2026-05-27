"""add tool_calls jsonb to dashboard_messages

Revision ID: 070
Revises: 069
Create Date: 2026-05-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "070"
down_revision: str | None = "069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dashboard_messages",
        sa.Column("tool_calls", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dashboard_messages", "tool_calls")
