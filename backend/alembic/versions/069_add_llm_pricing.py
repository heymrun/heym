"""add llm pricing tables and composite trace index

Revision ID: 069
Revises: 068
Create Date: 2026-05-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "069"
down_revision: str | None = "068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_pricing",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("operator", sa.String(20), nullable=False, server_default="equals"),
        sa.Column("input_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="helicone"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model", "operator", name="uq_llm_pricing_pmo"),
    )
    op.create_index("ix_llm_pricing_model", "llm_pricing", ["model"])

    op.create_table(
        "llm_pricing_override",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("input_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("base_pricing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_pricing_id"], ["llm_pricing.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "model", name="uq_llm_pricing_override_user_model"),
    )
    op.create_index("ix_llm_pricing_override_user", "llm_pricing_override", ["user_id"])

    op.create_index("ix_llm_traces_user_created", "llm_traces", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_traces_user_created", table_name="llm_traces")
    op.drop_index("ix_llm_pricing_override_user", table_name="llm_pricing_override")
    op.drop_table("llm_pricing_override")
    op.drop_index("ix_llm_pricing_model", table_name="llm_pricing")
    op.drop_table("llm_pricing")
