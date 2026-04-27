"""add credentials table

Revision ID: 003
Revises: 002
Create Date: 2026-01-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE credential_type AS ENUM ('openai', 'google', 'custom', 'header')")

    op.create_table(
        "credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(
                "openai", "google", "custom", "header", name="credential_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "name", name="uq_credential_name"),
    )
    op.create_index("ix_credentials_name", "credentials", ["name"])
    op.create_index("ix_credentials_owner_id", "credentials", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_credentials_owner_id", table_name="credentials")
    op.drop_index("ix_credentials_name", table_name="credentials")
    op.drop_table("credentials")
    op.execute("DROP TYPE credential_type")
