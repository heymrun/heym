"""Merge Notion and pgvector migration heads.

Revision ID: 082_merge_notion_pgvector_heads
Revises: 081_add_notion_credential_type, 9cbd3c82d23b
Create Date: 2026-06-22 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "082_merge_notion_pgvector_heads"
down_revision: tuple[str, str] = (
    "081_add_notion_credential_type",
    "9cbd3c82d23b",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the Notion and pgvector migration branches."""


def downgrade() -> None:
    """Split the migration graph back into its parent branches."""
