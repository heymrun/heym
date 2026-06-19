"""merge github and supabase migration heads

Revision ID: 080_merge_github_supabase_heads
Revises: 077_add_github_credential_type, 079_add_supabase_credential_type
Create Date: 2026-06-18
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "080_merge_github_supabase_heads"
down_revision: tuple[str, str] = (
    "077_add_github_credential_type",
    "079_add_supabase_credential_type",
)
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
