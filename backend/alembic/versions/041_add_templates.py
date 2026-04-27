"""Add workflow_templates and node_templates tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "041"
down_revision: str | None = "040"
branch_labels: str | None = None
depends_on: str | None = None


_visibility_enum = postgresql.ENUM(
    "everyone", "specific_users", name="template_visibility", create_type=False
)


def upgrade() -> None:
    # Create enum type only if it doesn't already exist
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'template_visibility') THEN "
        "CREATE TYPE template_visibility AS ENUM ('everyone', 'specific_users'); "
        "END IF; "
        "END $$"
    )

    op.create_table(
        "workflow_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("tags", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("nodes", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("edges", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("canvas_snapshot", sa.Text, nullable=True),
        sa.Column("visibility", _visibility_enum, nullable=False, server_default="everyone"),
        sa.Column("shared_with", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_workflow_templates_name", "workflow_templates", ["name"])
    op.create_index("ix_workflow_templates_created_at", "workflow_templates", ["created_at"])

    op.create_table(
        "node_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("tags", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("node_type", sa.String(100), nullable=False),
        sa.Column("node_data", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("visibility", _visibility_enum, nullable=False, server_default="everyone"),
        sa.Column("shared_with", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_node_templates_name", "node_templates", ["name"])
    op.create_index("ix_node_templates_created_at", "node_templates", ["created_at"])


def downgrade() -> None:
    op.drop_table("node_templates")
    op.drop_table("workflow_templates")
    op.execute("DROP TYPE IF EXISTS template_visibility")
