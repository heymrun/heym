"""add workflow_timeout_seconds to workflows

Revision ID: 089_workflow_timeout
Revises: 088_error_wf_time_saved
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "089_workflow_timeout"
down_revision: str | None = "088_error_wf_time_saved"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("workflow_timeout_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflows", "workflow_timeout_seconds")
