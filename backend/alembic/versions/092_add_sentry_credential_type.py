"""add sentry credential type

Revision ID: 092_add_sentry_credential_type
Revises: 091_dashboard_chat_queue
Create Date: 2026-06-29
"""

from alembic import op

revision: str = "092_add_sentry_credential_type"
down_revision: str | None = "091_dashboard_chat_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'sentry'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
