"""add user tts preferences

Revision ID: 073
Revises: 072
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "073"
down_revision: str | None = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tts_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("users", sa.Column("tts_voice_id", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_users_tts_credential_id",
        "users",
        "credentials",
        ["tts_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_tts_credential_id", "users", type_="foreignkey")
    op.drop_column("users", "tts_voice_id")
    op.drop_column("users", "tts_credential_id")
