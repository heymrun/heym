"""add workflow_execution_tokens table

Revision ID: 060
Revises: 059_add_telegram_credential_type
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "060"
down_revision: str = "059_add_telegram_credential_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_execution_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jti", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("jti", name="uq_workflow_execution_token_jti"),
    )
    op.create_index("ix_workflow_execution_tokens_jti", "workflow_execution_tokens", ["jti"])
    op.create_index(
        "ix_workflow_execution_tokens_user_id", "workflow_execution_tokens", ["user_id"]
    )
    op.create_index(
        "ix_workflow_execution_tokens_workflow_id", "workflow_execution_tokens", ["workflow_id"]
    )


def downgrade() -> None:
    op.drop_table("workflow_execution_tokens")
