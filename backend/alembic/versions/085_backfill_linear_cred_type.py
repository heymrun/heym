"""backfill linear credential type for databases that skipped the linear branch

Revision ID: 085_backfill_linear_cred_type
Revises: 084_add_clickhouse_cred_type
Create Date: 2026-06-28

Some databases reached 084 via 082 -> 083_add_file_upload_slots before the migration
graph was rewired to require 9d1f2a3b4c5d. Alembic reported head without ever
running the linear enum migration on those databases.
"""

from alembic import op

revision: str = "085_backfill_linear_cred_type"
down_revision: str | None = "084_add_clickhouse_cred_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'linear'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
