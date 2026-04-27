"""Add reasoning_effort to eval_runs for reasoning models (gpt-5, o1, o3)

Reasoning models use reasoning_effort instead of temperature.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "039"
down_revision: str | None = "038"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("reasoning_effort", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "reasoning_effort")
