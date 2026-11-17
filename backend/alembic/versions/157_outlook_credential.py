"""Add the Outlook (Microsoft Graph) OAuth credential type.

Revision ID: 157_outlook_credential
Revises: 156_gmail_credential
"""

from alembic import op

revision: str = "157_outlook_credential"
down_revision: str = "156_gmail_credential"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Extend the existing PostgreSQL enum without modifying stored credentials."""
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'outlook'")


def downgrade() -> None:
    """PostgreSQL cannot remove an enum value without recreating the type."""
