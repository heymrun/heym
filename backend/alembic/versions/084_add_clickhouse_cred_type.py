"""add clickhouse credential type

Revision ID: 084
Revises: 083_add_file_upload_slots
Create Date: 2026-06-27
"""

from alembic import op

revision: str = "084_add_clickhouse_cred_type"
down_revision: str | None = "083_add_file_upload_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'clickhouse'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
