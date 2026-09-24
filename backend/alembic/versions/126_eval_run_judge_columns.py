"""add judge columns to eval_runs

Revision ID: 126_eval_run_judge_cols
Revises: 125_llm_trace_router_cols
Create Date: 2026-09-23 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "126_eval_run_judge_cols"
down_revision: Union[str, None] = "125_llm_trace_router_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("judge_credential_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("eval_runs", sa.Column("judge_model", sa.String(length=255), nullable=True))
    op.create_index("ix_eval_runs_judge_credential_id", "eval_runs", ["judge_credential_id"])
    op.create_foreign_key(
        "fk_eval_runs_judge_credential_id",
        "eval_runs",
        "credentials",
        ["judge_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_eval_runs_judge_credential_id", "eval_runs", type_="foreignkey")
    op.drop_index("ix_eval_runs_judge_credential_id", table_name="eval_runs")
    op.drop_column("eval_runs", "judge_model")
    op.drop_column("eval_runs", "judge_credential_id")
