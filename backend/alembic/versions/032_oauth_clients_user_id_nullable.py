"""make oauth_clients.user_id nullable for dynamic client registration

OAuth 2.0 dynamic client registration creates clients without a user;
users authorize later. The user_id column may exist from a different
schema—make it nullable so registration works.

Revision ID: 032
Revises: 031
Create Date: 2026-03-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "032"
down_revision: str | None = "031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'oauth_clients'
              AND column_name = 'user_id'
          ) THEN
            ALTER TABLE oauth_clients ALTER COLUMN user_id DROP NOT NULL;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Cannot safely restore NOT NULL if rows have NULL user_id
    pass
