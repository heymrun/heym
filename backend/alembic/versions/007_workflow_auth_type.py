"""Add workflow auth type enum and fields

Revision ID: 007
Revises: 006
Create Date: 2026-01-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    workflow_auth_type = sa.Enum("anonymous", "jwt", "header_auth", name="workflow_auth_type")
    workflow_auth_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "workflows",
        sa.Column(
            "auth_type",
            sa.Enum("anonymous", "jwt", "header_auth", name="workflow_auth_type"),
            nullable=True,
        ),
    )
    op.add_column(
        "workflows",
        sa.Column("auth_header_key", sa.String(255), nullable=True),
    )
    op.add_column(
        "workflows",
        sa.Column("auth_header_value", sa.String(1024), nullable=True),
    )

    op.execute(
        """
        UPDATE workflows
        SET auth_type = CASE
            WHEN allow_anonymous = true THEN 'anonymous'::workflow_auth_type
            ELSE 'jwt'::workflow_auth_type
        END
        """
    )

    op.alter_column("workflows", "auth_type", nullable=False, server_default="jwt")

    op.drop_column("workflows", "allow_anonymous")


def downgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("allow_anonymous", sa.Boolean(), nullable=True, server_default="false"),
    )

    op.execute(
        """
        UPDATE workflows
        SET allow_anonymous = CASE
            WHEN auth_type = 'anonymous' THEN true
            ELSE false
        END
        """
    )

    op.alter_column("workflows", "allow_anonymous", nullable=False)

    op.drop_column("workflows", "auth_header_value")
    op.drop_column("workflows", "auth_header_key")
    op.drop_column("workflows", "auth_type")

    op.execute("DROP TYPE IF EXISTS workflow_auth_type")
