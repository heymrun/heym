"""add jira credential type

Revision ID: 095_add_jira_credential_type
Revises: 093_add_codex_node_support
Create Date: 2026-07-06 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "095_add_jira_credential_type"
down_revision: str | Sequence[str] | None = "093_add_codex_node_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'jira'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without rebuilding the type.
    pass
