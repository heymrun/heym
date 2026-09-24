"""Add dashboard user/team sharing.

Revision ID: 127_add_dashboard_shares
Revises: 126_eval_run_judge_cols
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "127_add_dashboard_shares"
down_revision: Union[str, None] = "126_eval_run_judge_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dashboard_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dashboard_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dashboards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("dashboard_id", "user_id", name="uq_dashboard_share"),
    )
    op.create_index("ix_dashboard_shares_dashboard_id", "dashboard_shares", ["dashboard_id"])
    op.create_index("ix_dashboard_shares_user_id", "dashboard_shares", ["user_id"])

    op.create_table(
        "dashboard_team_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dashboard_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dashboards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("dashboard_id", "team_id", name="uq_dashboard_team_share"),
    )
    op.create_index(
        "ix_dashboard_team_shares_dashboard_id", "dashboard_team_shares", ["dashboard_id"]
    )
    op.create_index("ix_dashboard_team_shares_team_id", "dashboard_team_shares", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_dashboard_team_shares_team_id", table_name="dashboard_team_shares")
    op.drop_index("ix_dashboard_team_shares_dashboard_id", table_name="dashboard_team_shares")
    op.drop_table("dashboard_team_shares")
    op.drop_index("ix_dashboard_shares_user_id", table_name="dashboard_shares")
    op.drop_index("ix_dashboard_shares_dashboard_id", table_name="dashboard_shares")
    op.drop_table("dashboard_shares")
