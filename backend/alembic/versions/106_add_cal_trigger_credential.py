"""Merge Cal.com migration history and add webhook delivery receipts.

Revision ID: 106_add_cal_trigger_credential
Revises: 105_add_rag_credential_type, 104_add_cal_trigger_credential
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "106_add_cal_trigger_credential"
down_revision: tuple[str, str] = (
    "105_add_rag_credential_type",
    "104_add_cal_trigger_credential",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add current Cal.com schema and clean up the retired managed-subscription table."""
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cal_api'")
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cal_trigger'")

    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "cal_webhook_delivery_receipts" not in table_names:
        op.create_table(
            "cal_webhook_delivery_receipts",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("workflow_id", sa.UUID(), nullable=False),
            sa.Column("node_id", sa.String(length=255), nullable=False),
            sa.Column("deduplication_key", sa.String(length=64), nullable=False),
            sa.Column("execution_id", sa.UUID(), nullable=False),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("execution_id"),
            sa.UniqueConstraint(
                "workflow_id",
                "node_id",
                "deduplication_key",
                name="uq_cal_webhook_delivery_receipt",
            ),
        )
        op.create_index(
            op.f("ix_cal_webhook_delivery_receipts_workflow_id"),
            "cal_webhook_delivery_receipts",
            ["workflow_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_cal_webhook_delivery_receipts_received_at"),
            "cal_webhook_delivery_receipts",
            ["received_at"],
            unique=False,
        )

    if "cal_webhook_subscriptions" in table_names:
        op.drop_table("cal_webhook_subscriptions")


def downgrade() -> None:
    """Remove the delivery receipt table while preserving enum values."""
    op.drop_index(
        op.f("ix_cal_webhook_delivery_receipts_received_at"),
        table_name="cal_webhook_delivery_receipts",
    )
    op.drop_index(
        op.f("ix_cal_webhook_delivery_receipts_workflow_id"),
        table_name="cal_webhook_delivery_receipts",
    )
    op.drop_table("cal_webhook_delivery_receipts")
    # PostgreSQL cannot remove enum values safely, so cal_api / cal_trigger remain.
