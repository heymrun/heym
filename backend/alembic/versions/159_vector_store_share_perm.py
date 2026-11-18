"""Give vector store shares a read or write permission.

Every share that already exists becomes ``read``.

Revision ID: 159_vector_store_share_perm
Revises: 158_outlook_calendar_credential
"""

import sqlalchemy as sa

from alembic import op

revision: str = "159_vector_store_share_perm"
down_revision: str = "158_outlook_calendar_credential"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Add ``permission`` to direct and team shares, defaulting to ``read``."""
    for table in ("vector_store_shares", "vector_store_team_shares"):
        op.add_column(
            table,
            sa.Column("permission", sa.String(10), nullable=False, server_default="read"),
        )


def downgrade() -> None:
    """Drop the permission columns."""
    for table in ("vector_store_team_shares", "vector_store_shares"):
        op.drop_column(table, "permission")
