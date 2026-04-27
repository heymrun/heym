"""add eval tables

Revision ID: 035
Revises: 034
Create Date: 2026-03-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_suites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("scoring_method", sa.String(50), nullable=False, server_default="exact_match"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_suites_owner_id", "eval_suites", ["owner_id"], unique=False)

    op.create_table(
        "eval_test_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected_output", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_mode", sa.String(20), nullable=False, server_default="text"),
        sa.Column("expected_mode", sa.String(20), nullable=False, server_default="text"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["suite_id"], ["eval_suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_test_cases_suite_id", "eval_test_cases", ["suite_id"], unique=False)

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("system_prompt_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "models", postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column("scoring_method", sa.String(50), nullable=False, server_default="exact_match"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["suite_id"], ["eval_suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_suite_id", "eval_runs", ["suite_id"], unique=False)

    op.create_table(
        "eval_run_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("test_case_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("input_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected_output_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("actual_output", sa.Text(), nullable=False, server_default=""),
        sa.Column("score", sa.String(20), nullable=False, server_default="fail"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["eval_test_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_run_results_run_id", "eval_run_results", ["run_id"], unique=False)
    op.create_index(
        "ix_eval_run_results_test_case_id", "eval_run_results", ["test_case_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_eval_run_results_test_case_id", table_name="eval_run_results")
    op.drop_index("ix_eval_run_results_run_id", table_name="eval_run_results")
    op.drop_table("eval_run_results")
    op.drop_index("ix_eval_runs_suite_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_test_cases_suite_id", table_name="eval_test_cases")
    op.drop_table("eval_test_cases")
    op.drop_index("ix_eval_suites_owner_id", table_name="eval_suites")
    op.drop_table("eval_suites")
