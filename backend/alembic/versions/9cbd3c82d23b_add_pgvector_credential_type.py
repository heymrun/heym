"""add_pgvector_credential_type

Revision ID: 9cbd3c82d23b
Revises: 5ba5b9aaf6ba
Create Date: 2026-06-22 12:56:47.002504

"""

from typing import Sequence, Union

from alembic import op

revision: str = "9cbd3c82d23b"
down_revision: Union[str, None] = "5ba5b9aaf6ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'pgvector'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
