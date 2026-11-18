"""board_card_runs.actor_user_id: the user a board run executes as

Revision ID: 160_board_card_run_actor
Revises: 159_vector_store_share_perm

A board run now uses the credentials, global variables and workflow access of the user who
moved, ran or answered the card. The column records that user so a chain that continues
later (auto-advance, a review answer, recovery after a restart) keeps running as them.

Existing rows stay null and keep running as the board owner, as they did when they started.
There is no foreign key, like ``active_workflow_executions.actor_user_id``: a run started by
a user who is later removed keeps their id, and its continuation finds no credentials and no
workflow access instead of falling back to someone else's.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "160_board_card_run_actor"
down_revision: str = "159_vector_store_share_perm"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Add the nullable ``actor_user_id`` column."""
    op.add_column(
        "board_card_runs",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    """Drop ``actor_user_id``; runs then use the board owner again."""
    op.drop_column("board_card_runs", "actor_user_id")
