"""eval run runs per test

Revision ID: 146_eval_run_runs_per_test
Revises: 145_suite_run_heartbeat
Create Date: 2026-10-26 00:00:00.000000

``eval_runs.runs_per_test`` stores the last setting a prompt suite run did not keep, so
the suite opens with all of them again. Existing runs get one run per test. The column
briefly lived in an edited 145, so the statements tolerate it already being there.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "146_eval_run_runs_per_test"
down_revision: str | Sequence[str] | None = "145_suite_run_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS runs_per_test INTEGER NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE eval_runs DROP COLUMN IF EXISTS runs_per_test")
