"""Merge Linear and Notion migration heads.

Revision ID: 083_merge_linear_notion_heads
Revises: 082_merge_notion_pgvector_heads, 9d1f2a3b4c5d
Create Date: 2026-06-25 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "083_merge_linear_notion_heads"
down_revision: tuple[str, str] = (
    "082_merge_notion_pgvector_heads",
    "9d1f2a3b4c5d",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the Linear and Notion migration branches."""


def downgrade() -> None:
    """Split the migration graph back into its parent branches."""
