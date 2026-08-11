"""add alerts

Revision ID: 108_add_alerts
Revises: 107_add_heym_events
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "108_add_alerts"
down_revision: str | Sequence[str] | None = "107_add_heym_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False, server_default="workflow"),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "notify_workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("renotify_mode", sa.String(20), nullable=False, server_default="on_recovery"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=True),
        sa.Column("check_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "next_check_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_alerts_owner_id", "alerts", ["owner_id"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_workflow_id", "alerts", ["workflow_id"])
    op.create_index("ix_alerts_enabled", "alerts", ["enabled"])
    op.create_index("ix_alerts_next_check_at", "alerts", ["next_check_at"])
    op.create_index("ix_alerts_enabled_next_check", "alerts", ["enabled", "next_check_at"])

    op.create_table(
        "alert_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notify_execution_id", UUID(as_uuid=True), nullable=True),
        sa.Column("notify_status", sa.String(20), nullable=True),
    )
    op.create_index("ix_alert_events_alert_id", "alert_events", ["alert_id"])
    op.create_index("ix_alert_events_triggered_at", "alert_events", ["triggered_at"])
    op.create_index("ix_alert_events_alert_triggered", "alert_events", ["alert_id", "triggered_at"])

    op.create_table(
        "alert_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("alert_id", "user_id", name="uq_alert_share"),
    )

    op.create_table(
        "alert_team_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("alert_id", "team_id", name="uq_alert_team_share"),
    )
    op.create_index("ix_alert_team_shares_alert_id", "alert_team_shares", ["alert_id"])
    op.create_index("ix_alert_team_shares_team_id", "alert_team_shares", ["team_id"])


def downgrade() -> None:
    op.drop_table("alert_team_shares")
    op.drop_table("alert_shares")
    op.drop_table("alert_events")
    op.drop_table("alerts")
