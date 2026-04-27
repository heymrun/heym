"""Add cache and rate limit fields to workflows

Revision ID: 012
Revises: 011_add_redis_credential_type
Create Date: 2026-01-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("cache_ttl_seconds", sa.Integer(), nullable=True))
    op.add_column("workflows", sa.Column("rate_limit_requests", sa.Integer(), nullable=True))
    op.add_column("workflows", sa.Column("rate_limit_window_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflows", "rate_limit_window_seconds")
    op.drop_column("workflows", "rate_limit_requests")
    op.drop_column("workflows", "cache_ttl_seconds")
