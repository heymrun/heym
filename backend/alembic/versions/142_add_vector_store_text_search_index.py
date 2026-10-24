"""full-text index on vector_store_items.text for hybrid search

Revision ID: 142_vsi_text_search_index
Revises: 141_add_credential_setup
Create Date: 2026-10-24 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "142_vsi_text_search_index"
down_revision: Union[str, None] = "141_add_credential_setup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector is opt-in: the table only exists where 5ba5b9aaf6ba could create it.
    # The expression must match app.services.vector_store_pg.TEXT_SEARCH_SQL, or the
    # planner ignores the index. Hybrid search still works without it, only slower.
    op.execute(
        r"""
        DO $$
        BEGIN
            IF to_regclass('public.vector_store_items') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS ix_vsi_text_search
                ON vector_store_items
                USING gin (to_tsvector('simple', regexp_replace(left(text, 200000), '(\W|_)+', ' ', 'g')));
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vsi_text_search")
