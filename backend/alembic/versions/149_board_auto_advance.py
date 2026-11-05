"""boards.auto_advance: whether a card moves to the next column on its own

Revision ID: 149_board_auto_advance
Revises: 148_node_analytics
Create Date: 2026-11-05 00:00:00.000000

Existing boards keep today's behavior, so every row starts true. A board used as a plain
team task list turns it off and cards then stay where people put them.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "149_board_auto_advance"
down_revision: str | Sequence[str] | None = "148_node_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column("auto_advance", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("boards", "auto_advance")
