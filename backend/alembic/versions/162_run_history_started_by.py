"""execution_history.executed_by_user_id: the user who started a run

Revision ID: 162_run_history_started_by
Revises: 161_run_history_encryption

History shows who started a run. The column is set for runs a signed-in user starts (the
editor, an API key, an execution token, MCP, boards); a cron, webhook or messaging trigger
has no user and leaves it null.

Existing rows stay null: nothing records who started them. Deleting a user nulls the column.
Downgrade drops it, and the attribution with it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "162_run_history_started_by"
down_revision: str = "161_run_history_encryption"
branch_labels: None = None
depends_on: None = None

_FK_NAME = "fk_execution_history_executed_by_user_id"


def upgrade() -> None:
    """Add the nullable column and its foreign key."""
    op.add_column(
        "execution_history",
        sa.Column("executed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        _FK_NAME,
        "execution_history",
        "users",
        ["executed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Drop the column; runs lose their attribution."""
    op.drop_constraint(_FK_NAME, "execution_history", type_="foreignkey")
    op.drop_column("execution_history", "executed_by_user_id")
