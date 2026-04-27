"""Preserve eval_run_results when test case is deleted (SET NULL instead of CASCADE)

When a test case is deleted, run results that reference it should be preserved
for history. Change FK to SET NULL so results remain with their snapshots.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(
        "eval_run_results_test_case_id_fkey",
        "eval_run_results",
        type_="foreignkey",
    )
    op.alter_column(
        "eval_run_results",
        "test_case_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_foreign_key(
        "eval_run_results_test_case_id_fkey",
        "eval_run_results",
        "eval_test_cases",
        ["test_case_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "eval_run_results_test_case_id_fkey",
        "eval_run_results",
        type_="foreignkey",
    )
    op.alter_column(
        "eval_run_results",
        "test_case_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "eval_run_results_test_case_id_fkey",
        "eval_run_results",
        "eval_test_cases",
        ["test_case_id"],
        ["id"],
        ondelete="CASCADE",
    )
