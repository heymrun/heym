"""add file upload slots and audit

Revision ID: 083_add_file_upload_slots
Revises: 082_merge_notion_pgvector_heads
Create Date: 2026-06-25 19:55:21.516061

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "083_add_file_upload_slots"
down_revision: Union[str, None] = "082_merge_notion_pgvector_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_upload_audit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slot_id", sa.UUID(), nullable=True),
        sa.Column("workflow_id", sa.UUID(), nullable=True),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("mime", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_file_upload_audit_slot_id"), "file_upload_audit", ["slot_id"], unique=False
    )
    op.create_index(
        op.f("ix_file_upload_audit_workflow_id"),
        "file_upload_audit",
        ["workflow_id"],
        unique=False,
    )
    op.create_table(
        "file_upload_slots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("max_size_bytes", sa.Integer(), nullable=False),
        sa.Column("allowed_mime", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("trigger_node_id", sa.String(length=64), nullable=False),
        sa.Column("trigger_node_label", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_file_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("mint_source", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["generated_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_file_upload_slots_token_hash"),
        "file_upload_slots",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_file_upload_slots_workflow_id"),
        "file_upload_slots",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_file_upload_slots_workflow_id"), table_name="file_upload_slots")
    op.drop_index(op.f("ix_file_upload_slots_token_hash"), table_name="file_upload_slots")
    op.drop_table("file_upload_slots")
    op.drop_index(op.f("ix_file_upload_audit_workflow_id"), table_name="file_upload_audit")
    op.drop_index(op.f("ix_file_upload_audit_slot_id"), table_name="file_upload_audit")
    op.drop_table("file_upload_audit")
