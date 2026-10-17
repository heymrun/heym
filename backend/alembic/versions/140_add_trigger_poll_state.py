"""add trigger poll state for Google Drive and Google Sheets triggers

Revision ID: 140_add_trigger_poll_state
Revises: 139_add_slack_bot_credential
Create Date: 2026-10-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "140_add_trigger_poll_state"
down_revision: str | Sequence[str] | None = "139_add_slack_bot_credential"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trigger_poll_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("key_id", sa.String(32), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "next_poll_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "node_id", name="uq_trigger_poll_state_node"),
    )
    op.create_index("ix_trigger_poll_states_workflow_id", "trigger_poll_states", ["workflow_id"])
    op.create_index("ix_trigger_poll_states_next_poll_at", "trigger_poll_states", ["next_poll_at"])

    op.create_table(
        "trigger_poll_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "state_id",
            UUID(as_uuid=True),
            sa.ForeignKey("trigger_poll_states.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_key", sa.String(255), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("state_id", "item_key", name="uq_trigger_poll_item_key"),
    )


def downgrade() -> None:
    op.drop_table("trigger_poll_items")
    op.drop_index("ix_trigger_poll_states_next_poll_at", table_name="trigger_poll_states")
    op.drop_index("ix_trigger_poll_states_workflow_id", table_name="trigger_poll_states")
    op.drop_table("trigger_poll_states")
