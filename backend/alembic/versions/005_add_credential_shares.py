"""add credential shares table

Revision ID: 005
Revises: 004
Create Date: 2026-01-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "credential_id",
            UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("credential_id", "user_id", name="uq_credential_share"),
    )


def downgrade() -> None:
    op.drop_table("credential_shares")
