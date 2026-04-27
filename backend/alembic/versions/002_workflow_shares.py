from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "user_id", name="uq_workflow_share"),
    )
    op.create_index("ix_workflow_shares_user_id", "workflow_shares", ["user_id"])
    op.create_index("ix_workflow_shares_workflow_id", "workflow_shares", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_shares_workflow_id", table_name="workflow_shares")
    op.drop_index("ix_workflow_shares_user_id", table_name="workflow_shares")
    op.drop_table("workflow_shares")
