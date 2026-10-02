"""Add a read/write permission to direct and team workflow shares.

Every share that exists before this migration was granted when a collaborator could
always edit, so the column is backfilled (through the server default) to ``write``.
Downgrade drops the column; shares keep working but lose their read-only restriction.

Revision ID: 129_workflow_share_permission
Revises: 128_workflow_share_explicit_flag
Create Date: 2026-10-02
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "129_workflow_share_permission"
down_revision: Union[str, None] = "128_workflow_share_explicit_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("workflow_shares", "workflow_team_shares"):
        op.add_column(
            table,
            sa.Column("permission", sa.String(10), nullable=False, server_default="write"),
        )


def downgrade() -> None:
    for table in ("workflow_team_shares", "workflow_shares"):
        op.drop_column(table, "permission")
