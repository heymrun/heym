"""Make oauth_clients.client_secret_hash nullable.

Public MCP clients (token_endpoint_auth_method=none) have no secret, so
client_secret_hash is legitimately NULL.  The column was created with NOT NULL
on older production deployments because the original migration used
if_not_exists=True and the pre-existing table had a stricter constraint.

Fix: unconditionally drop the NOT NULL constraint so public-client OAuth
Dynamic Client Registration (POST /register) no longer fails with
NotNullViolationError.
"""

from alembic import op

revision: str = "051"
down_revision: str | None = "050"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE oauth_clients
        ALTER COLUMN client_secret_hash DROP NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE oauth_clients
        ALTER COLUMN client_secret_hash SET NOT NULL
        """
    )
