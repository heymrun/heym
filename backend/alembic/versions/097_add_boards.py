"""Add agentic kanban board tables.

Revision ID: 097_add_boards
Revises: 096_merge_jira_file_heads
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "097_add_boards"
down_revision: Union[str, None] = "096_merge_jira_file_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "board_columns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "board_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boards.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "board_column_workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "column_id",
            UUID(as_uuid=True),
            sa.ForeignKey("board_columns.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("column_id", "workflow_id", name="uq_board_column_workflow"),
    )
    op.create_table(
        "board_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "board_id",
            UUID(as_uuid=True),
            sa.ForeignKey("boards.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "column_id",
            UUID(as_uuid=True),
            sa.ForeignKey("board_columns.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("card_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "board_card_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "card_id",
            UUID(as_uuid=True),
            sa.ForeignKey("board_cards.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "column_id",
            UUID(as_uuid=True),
            sa.ForeignKey("board_columns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workflow_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("chain_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chain_length", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running", index=True),
        sa.Column(
            "execution_history_id",
            UUID(as_uuid=True),
            sa.ForeignKey("execution_history.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "board_card_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "card_id",
            UUID(as_uuid=True),
            sa.ForeignKey("board_cards.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(20), nullable=False, server_default="event"),
        sa.Column("author_type", sa.String(20), nullable=False, server_default="system"),
        sa.Column("author_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("board_card_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
        ),
    )


def downgrade() -> None:
    op.drop_table("board_card_activities")
    op.drop_table("board_card_runs")
    op.drop_table("board_cards")
    op.drop_table("board_column_workflows")
    op.drop_table("board_columns")
    op.drop_table("boards")
