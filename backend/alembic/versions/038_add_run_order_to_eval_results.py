"""Add run_order to eval_run_results for preserving editor order

Results are created in parallel (asyncio.gather), so created_at order does not
match test case order_index. run_order stores the intended order at creation.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "eval_run_results",
        sa.Column("run_order", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_run_results", "run_order")
