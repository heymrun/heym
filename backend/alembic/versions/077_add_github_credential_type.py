"""add github credential type

Revision ID: 077_add_github_credential_type
Revises: 076_discord_trigger_credential
Create Date: 2026-06-12 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "077_add_github_credential_type"
down_revision: str | Sequence[str] | None = "078_merge_s3_dashboard_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'github'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in a simple downgrade.
    pass
