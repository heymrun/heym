"""Merge Jira and file team share migration heads.

Revision ID: 096_merge_jira_file_heads
Revises: 095_add_jira_credential_type, 094_add_file_team_shares
Create Date: 2026-07-09 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "096_merge_jira_file_heads"
down_revision: tuple[str, str] = (
    "095_add_jira_credential_type",
    "094_add_file_team_shares",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the Jira and file team share migration branches."""


def downgrade() -> None:
    """Split the migration graph back into its parent branches."""
