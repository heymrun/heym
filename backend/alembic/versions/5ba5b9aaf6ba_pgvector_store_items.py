"""pgvector_store_items

Revision ID: 5ba5b9aaf6ba
Revises: 081_add_workflow_analysis_notes
Create Date: 2026-06-22 12:55:50.484853

"""

import logging
from typing import Sequence, Union

from alembic import op

revision: str = "5ba5b9aaf6ba"
down_revision: Union[str, None] = "081_add_workflow_analysis_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.pgvector_store_items")


def upgrade() -> None:
    bind = op.get_bind()

    # The pgvector backend is opt-in (Qdrant remains the default). On a Postgres
    # that does not ship the `vector` extension (e.g. some managed databases),
    # creating it would abort the whole migration and block the deploy. Detect
    # availability first and skip gracefully so existing deployments are never
    # broken — Qdrant RAG keeps working, and this table can be created later
    # once pgvector is provisioned (re-stamp this revision and re-run, or apply
    # the DDL below manually).
    available = bind.exec_driver_sql(
        "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
    ).scalar()
    if not available:
        logger.warning(
            "pgvector extension is not available on this database; skipping "
            "vector_store_items table. The Postgres vector store backend will be "
            "unavailable until pgvector is installed. Qdrant RAG is unaffected."
        )
        return

    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as exc:  # pragma: no cover - depends on DB privileges
        logger.warning(
            "Could not create the pgvector extension (%s); skipping "
            "vector_store_items table. Qdrant RAG is unaffected.",
            exc,
        )
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_store_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            collection_name TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            source TEXT,
            file_size INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vsi_collection_name ON vector_store_items (collection_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vsi_collection_source "
        "ON vector_store_items (collection_name, source)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vsi_embedding_hnsw "
        "ON vector_store_items USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vector_store_items")
