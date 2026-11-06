"""Add the Google Meet OAuth credential type.

Revision ID: 150_google_meet_credential
Revises: 149_board_auto_advance
"""

from alembic import op

revision: str = "150_google_meet_credential"
down_revision: str = "149_board_auto_advance"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Extend the existing PostgreSQL enum without modifying stored credentials."""
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'google_meet'")


def downgrade() -> None:
    """PostgreSQL cannot remove an enum value without recreating the type."""
