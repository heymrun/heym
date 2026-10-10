"""add row links to dashboard widgets

Revision ID: 134_add_dashboard_widget_links
Revises: 133_add_dashboard_record_pages
Create Date: 2026-10-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "134_add_dashboard_widget_links"
down_revision: Union[str, None] = "133_add_dashboard_record_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboard_widgets",
        sa.Column(
            "link_dashboard_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "dashboards.id",
                ondelete="SET NULL",
                name="fk_dashboard_widgets_link_dashboard_id",
            ),
            nullable=True,
        ),
    )
    op.add_column("dashboard_widgets", sa.Column("link_record_field", sa.String(255)))
    op.add_column("dashboard_widgets", sa.Column("link_label_field", sa.String(255)))


def downgrade() -> None:
    op.drop_column("dashboard_widgets", "link_label_field")
    op.drop_column("dashboard_widgets", "link_record_field")
    op.drop_column("dashboard_widgets", "link_dashboard_id")
