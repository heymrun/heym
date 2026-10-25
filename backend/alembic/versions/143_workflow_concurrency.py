"""per-workflow concurrency limit

Revision ID: 143_workflow_concurrency
Revises: 142_vsi_text_search_index
Create Date: 2026-10-25 00:00:00.000000

status_token_hash is a new, empty column: there is no plaintext to backfill. The
token it stores the digest of is secrets.token_urlsafe(32), which is shape-distinct
from a SHA-256 hex digest. Downgrade drops the column; nothing can be restored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "143_workflow_concurrency"
down_revision: str | Sequence[str] | None = "142_vsi_text_search_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("concurrency_limit", sa.Integer(), nullable=True))
    op.add_column("workflows", sa.Column("concurrency_max_queue", sa.Integer(), nullable=True))
    op.add_column(
        "workflows", sa.Column("concurrency_max_wait_seconds", sa.Integer(), nullable=True)
    )
    op.create_table(
        "workflow_concurrency_slots",
        sa.Column("execution_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_workflow_concurrency_slots_workflow_id",
        "workflow_concurrency_slots",
        ["workflow_id"],
    )
    op.execute("CREATE SEQUENCE IF NOT EXISTS workflow_concurrency_seq")
    op.add_column(
        "workflow_run_queue", sa.Column("concurrency_seq", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "workflow_run_queue", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "workflow_run_queue", sa.Column("status_token_hash", sa.String(64), nullable=True)
    )
    op.add_column("workflow_run_queue", sa.Column("run_options", sa.JSON(), nullable=True))
    op.create_index(
        "ix_workflow_run_queue_concurrency",
        "workflow_run_queue",
        ["workflow_id", "status", "concurrency_seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_run_queue_concurrency", table_name="workflow_run_queue")
    op.drop_column("workflow_run_queue", "run_options")
    op.drop_column("workflow_run_queue", "status_token_hash")
    op.drop_column("workflow_run_queue", "expires_at")
    op.drop_column("workflow_run_queue", "concurrency_seq")
    op.execute("DROP SEQUENCE IF EXISTS workflow_concurrency_seq")
    op.drop_index(
        "ix_workflow_concurrency_slots_workflow_id", table_name="workflow_concurrency_slots"
    )
    op.drop_table("workflow_concurrency_slots")
    op.drop_column("workflows", "concurrency_max_wait_seconds")
    op.drop_column("workflows", "concurrency_max_queue")
    op.drop_column("workflows", "concurrency_limit")
