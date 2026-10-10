"""add dashboard detail-page record format and per-record widget cache

Revision ID: 133_add_dashboard_record_pages
Revises: 132_add_chat_build_queue_fields
Create Date: 2026-10-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "133_add_dashboard_record_pages"
down_revision: Union[str, None] = "132_add_chat_build_queue_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboards",
        sa.Column("record_format", sa.String(16), nullable=False, server_default="id"),
    )
    op.create_table(
        "dashboard_widget_record_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "widget_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dashboard_widgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("record", sa.String(128), nullable=False),
        sa.Column("payload", JSON(), nullable=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cached_workflow_version", sa.String(64), nullable=True),
        sa.UniqueConstraint("widget_id", "record", name="uq_dashboard_widget_record_cache"),
    )
    op.create_index(
        "ix_dashboard_widget_record_cache_widget_id",
        "dashboard_widget_record_cache",
        ["widget_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dashboard_widget_record_cache_widget_id", table_name="dashboard_widget_record_cache"
    )
    op.drop_table("dashboard_widget_record_cache")
    op.drop_column("dashboards", "record_format")
