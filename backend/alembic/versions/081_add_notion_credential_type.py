"""add notion credential type

Revision ID: 081_add_notion_credential_type
Revises: 080_merge_github_supabase_heads
Create Date: 2026-06-20
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "081_add_notion_credential_type"
down_revision: str | None = "080_merge_github_supabase_heads"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'notion'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
