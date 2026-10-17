"""add slack_bot credential type

Revision ID: 139_add_slack_bot_credential
Revises: 138_add_queue_trace_context
Create Date: 2026-10-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "139_add_slack_bot_credential"
down_revision: Union[str, None] = "138_add_queue_trace_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'slack_bot'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type.
    pass
