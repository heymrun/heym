"""Add webhook body mode to workflows and workflow versions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "047"
down_revision: str | None = "046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    webhook_body_mode = sa.Enum("legacy", "generic", name="webhook_body_mode")
    webhook_body_mode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "workflows",
        sa.Column(
            "webhook_body_mode",
            sa.Enum("legacy", "generic", name="webhook_body_mode"),
            nullable=True,
        ),
    )
    op.add_column(
        "workflow_versions",
        sa.Column(
            "webhook_body_mode",
            sa.Enum("legacy", "generic", name="webhook_body_mode"),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE workflows
        SET webhook_body_mode = 'legacy'::webhook_body_mode
        WHERE webhook_body_mode IS NULL
        """
    )
    op.execute(
        """
        UPDATE workflow_versions
        SET webhook_body_mode = 'legacy'::webhook_body_mode
        WHERE webhook_body_mode IS NULL
        """
    )

    op.alter_column(
        "workflows",
        "webhook_body_mode",
        nullable=False,
        server_default="legacy",
    )
    op.alter_column(
        "workflow_versions",
        "webhook_body_mode",
        nullable=False,
        server_default="legacy",
    )


def downgrade() -> None:
    op.drop_column("workflow_versions", "webhook_body_mode")
    op.drop_column("workflows", "webhook_body_mode")
    op.execute("DROP TYPE IF EXISTS webhook_body_mode")
