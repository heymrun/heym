"""board_card_runs.allow_advance: whether the chain may auto-advance once it finishes

Revision ID: 163_board_card_run_allow_advance
Revises: 162_run_history_started_by

A card moved back into a column, or run with "don't advance", runs that column's chain but
must not auto-advance. The chain knew this while it ran, but a chain that pauses for a review
or a Codex question finishes later, in the resume or recovery path, which read nothing and
advanced anyway. The column records the choice on each run so the continuation keeps it.

Existing rows default to true, the behaviour they had when they started.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "163_board_card_run_allow_advance"
down_revision: str = "162_run_history_started_by"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Add ``allow_advance``, true for existing rows."""
    op.add_column(
        "board_card_runs",
        sa.Column("allow_advance", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Drop ``allow_advance``; resumed chains then auto-advance again."""
    op.drop_column("board_card_runs", "allow_advance")
