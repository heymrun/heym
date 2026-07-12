"""Add board agentic mapper config (model/credential) and column AI instructions.

Revision ID: 098_add_board_mapper
Revises: 097_add_boards
Create Date: 2026-07-12
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "098_add_board_mapper"
down_revision: Union[str, None] = "097_add_boards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("boards", sa.Column("mapper_model", sa.String(128), nullable=True))
    op.add_column(
        "boards",
        sa.Column(
            "mapper_credential_id",
            UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("board_columns", sa.Column("ai_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("board_columns", "ai_instructions")
    op.drop_column("boards", "mapper_credential_id")
    op.drop_column("boards", "mapper_model")
