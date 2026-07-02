"""add dashboard chat queue

Revision ID: 091_dashboard_chat_queue
Revises: 090_add_plugins_table
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "091_dashboard_chat_queue"
down_revision: str | None = "090_add_plugins_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dashboard_conversations",
        sa.Column("queue_paused_by_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_dashboard_conversations_queue_paused_by_message_id",
        "dashboard_conversations",
        "dashboard_messages",
        ["queue_paused_by_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "dashboard_chat_queue_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dashboard_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("attachment", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_dashboard_chat_queue_items_conversation_id",
        "dashboard_chat_queue_items",
        ["conversation_id"],
    )
    op.create_index(
        "ix_dashboard_chat_queue_items_conv_created_id",
        "dashboard_chat_queue_items",
        ["conversation_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dashboard_chat_queue_items_conv_created_id",
        table_name="dashboard_chat_queue_items",
    )
    op.drop_index(
        "ix_dashboard_chat_queue_items_conversation_id",
        table_name="dashboard_chat_queue_items",
    )
    op.drop_table("dashboard_chat_queue_items")
    op.drop_constraint(
        "fk_dashboard_conversations_queue_paused_by_message_id",
        "dashboard_conversations",
        type_="foreignkey",
    )
    op.drop_column("dashboard_conversations", "queue_paused_by_message_id")
