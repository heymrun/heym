"""Vector store uploads read in the background.

Audio and PDFs with scanned pages take minutes to read, longer than an upload request should
stay open. Each such upload is a row here while it is read; the row is deleted once its chunks
are in the store, and a failed row keeps its error until it is dismissed.

Revision ID: 154_vector_store_ingest_jobs
Revises: 153_account_security
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "154_vector_store_ingest_jobs"
down_revision: str = "153_account_security"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "vector_store_ingest_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vector_store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vector_stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("override_duplicates", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_vector_store_ingest_jobs_store_status",
        "vector_store_ingest_jobs",
        ["vector_store_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_vector_store_ingest_jobs_store_status", table_name="vector_store_ingest_jobs")
    op.drop_table("vector_store_ingest_jobs")
