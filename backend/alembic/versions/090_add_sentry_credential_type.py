"""add sentry credential type

Revision ID: 090_add_sentry_credential_type
Revises: 089_workflow_timeout
Create Date: 2026-06-29
"""

from alembic import op

revision: str = "090_add_sentry_credential_type"
down_revision: str | None = "089_workflow_timeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'sentry'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
