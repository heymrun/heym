"""Add Cal.com Trigger credentials, delivery receipts, and managed subscriptions.

Revision ID: 104_add_cal_trigger_credential
Revises: 103_add_google_drive_cred_type
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "104_add_cal_trigger_credential"
down_revision: str | None = "103_add_google_drive_cred_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cal_api'")
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'cal_trigger'")

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

    op.create_table(
        "cal_webhook_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=True),
        sa.Column("external_webhook_id", sa.String(length=255), nullable=True),
        sa.Column("subscriber_url", sa.String(length=2048), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "node_id",
            name="uq_cal_webhook_subscription_node",
        ),
    )
    op.create_index(
        op.f("ix_cal_webhook_subscriptions_credential_id"),
        "cal_webhook_subscriptions",
        ["credential_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cal_webhook_subscriptions_status"),
        "cal_webhook_subscriptions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cal_webhook_subscriptions_workflow_id"),
        "cal_webhook_subscriptions",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_cal_webhook_subscriptions_workflow_id"),
        table_name="cal_webhook_subscriptions",
    )
    op.drop_index(
        op.f("ix_cal_webhook_subscriptions_status"),
        table_name="cal_webhook_subscriptions",
    )
    op.drop_index(
        op.f("ix_cal_webhook_subscriptions_credential_id"),
        table_name="cal_webhook_subscriptions",
    )
    op.drop_table("cal_webhook_subscriptions")

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
