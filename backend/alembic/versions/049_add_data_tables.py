"""Add data_tables, data_table_rows, data_table_shares, data_table_team_shares tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_tables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("columns", JSON, nullable=False, server_default="[]"),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_id", "name", name="uq_data_table_name"),
    )

    op.create_table(
        "data_table_rows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("data_tables.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("data", JSON, nullable=False, server_default="{}"),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "data_table_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("data_tables.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("permission", sa.String(10), nullable=False, server_default="read"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("table_id", "user_id", name="uq_data_table_share"),
    )

    op.create_table(
        "data_table_team_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("data_tables.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("permission", sa.String(10), nullable=False, server_default="read"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("table_id", "team_id", name="uq_data_table_team_share"),
    )


def downgrade() -> None:
    op.drop_table("data_table_team_shares")
    op.drop_table("data_table_shares")
    op.drop_table("data_table_rows")
    op.drop_table("data_tables")
