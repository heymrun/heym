"""add workflow http method

Revision ID: 114_add_workflow_http_method
Revises: 113_add_folder_description
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "114_add_workflow_http_method"
down_revision: str | None = "113_add_folder_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default is what keeps every existing workflow answering POST exactly as before.
    op.add_column(
        "workflows",
        sa.Column("http_method", sa.String(8), nullable=False, server_default="POST"),
    )


def downgrade() -> None:
    op.drop_column("workflows", "http_method")
