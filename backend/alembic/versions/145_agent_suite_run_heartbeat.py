"""agent suite run heartbeat, eval run credential

Revision ID: 145_suite_run_heartbeat
Revises: 144_add_agent_suites
Create Date: 2026-10-26 00:00:00.000000

A running suite run writes ``heartbeat_at`` every few seconds; a row whose heartbeat went
quiet lost its runner, for example to a server restart, and is closed as interrupted.

``eval_runs.credential_id`` and ``eval_runs.runs_per_test`` record the rest of a prompt
suite run's settings, so the suite opens with them again. Existing runs keep a NULL
credential (it was never stored) and one run per test.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "145_suite_run_heartbeat"
down_revision: str | Sequence[str] | None = "144_add_agent_suites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_suite_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "eval_runs",
        sa.Column(
            "credential_id",
            UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_eval_runs_credential_id", "eval_runs", ["credential_id"])
    op.add_column(
        "eval_runs",
        sa.Column("runs_per_test", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "runs_per_test")
    op.drop_index("ix_eval_runs_credential_id", table_name="eval_runs")
    op.drop_column("eval_runs", "credential_id")
    op.drop_column("agent_suite_runs", "heartbeat_at")
