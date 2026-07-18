"""add user preferred ai defaults

Revision ID: 101_add_user_ai_defaults
Revises: 100_add_opencode_credential_type
Create Date: 2026-07-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "101_add_user_ai_defaults"
down_revision: Union[str, None] = "100_add_opencode_credential_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferred_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("users", sa.Column("preferred_model", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_users_preferred_credential_id",
        "users",
        "credentials",
        ["preferred_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_preferred_credential_id", "users", type_="foreignkey")
    op.drop_column("users", "preferred_model")
    op.drop_column("users", "preferred_credential_id")
