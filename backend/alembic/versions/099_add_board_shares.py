"""Add board user/team sharing.

Revision ID: 099_add_board_shares
Revises: 098_add_board_mapper
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "099_add_board_shares"
down_revision: Union[str, None] = "098_add_board_mapper"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "board_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "board_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("board_id", "user_id", name="uq_board_share"),
    )
    op.create_index("ix_board_shares_board_id", "board_shares", ["board_id"])
    op.create_index("ix_board_shares_user_id", "board_shares", ["user_id"])

    op.create_table(
        "board_team_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "board_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(length=10), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("board_id", "team_id", name="uq_board_team_share"),
    )
    op.create_index("ix_board_team_shares_board_id", "board_team_shares", ["board_id"])
    op.create_index("ix_board_team_shares_team_id", "board_team_shares", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_board_team_shares_team_id", table_name="board_team_shares")
    op.drop_index("ix_board_team_shares_board_id", table_name="board_team_shares")
    op.drop_table("board_team_shares")
    op.drop_index("ix_board_shares_user_id", table_name="board_shares")
    op.drop_index("ix_board_shares_board_id", table_name="board_shares")
    op.drop_table("board_shares")
