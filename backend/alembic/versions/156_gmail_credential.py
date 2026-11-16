"""Add the Gmail OAuth credential type.

Revision ID: 156_gmail_credential
Revises: 155_mcp_server_endpoint_path
"""

from alembic import op

revision: str = "156_gmail_credential"
down_revision: str = "155_mcp_server_endpoint_path"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Extend the existing PostgreSQL enum without modifying stored credentials."""
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'gmail'")


def downgrade() -> None:
    """PostgreSQL cannot remove an enum value without recreating the type."""
