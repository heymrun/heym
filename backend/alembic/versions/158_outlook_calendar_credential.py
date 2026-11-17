"""Add the Outlook Calendar (Microsoft Graph) OAuth credential type.

Revision ID: 158_outlook_calendar_credential
Revises: 157_outlook_credential
"""

from alembic import op

revision: str = "158_outlook_calendar_credential"
down_revision: str = "157_outlook_credential"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Extend the existing PostgreSQL enum without modifying stored credentials."""
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'outlook_calendar'")


def downgrade() -> None:
    """PostgreSQL cannot remove an enum value without recreating the type."""
