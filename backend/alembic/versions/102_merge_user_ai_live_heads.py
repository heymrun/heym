"""Merge user AI defaults and live execution snapshot heads.

Revision ID: 102_merge_user_ai_live_heads
Revises: 101_add_user_ai_defaults, 101_add_live_execution_snapshots
Create Date: 2026-07-18
"""

from collections.abc import Sequence

revision: str = "102_merge_user_ai_live_heads"
down_revision: tuple[str, str] = (
    "101_add_user_ai_defaults",
    "101_add_live_execution_snapshots",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
