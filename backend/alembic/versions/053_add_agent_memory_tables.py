"""Add agent_memory_nodes and agent_memory_edges for agent persistent memory.

Drops any prior agent_memory_* tables first so broken or legacy schemas (e.g. missing
canvas_node_id) are replaced cleanly on upgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "053"
down_revision: str | None = "052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove legacy or partial installs (wrong columns, failed mid-migration, etc.)
    op.execute(sa.text("DROP TABLE IF EXISTS agent_memory_edges CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS agent_memory_nodes CASCADE"))

    op.create_table(
        "agent_memory_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canvas_node_id", sa.String(128), nullable=False),
        sa.Column("entity_name", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("properties", JSON, nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_agent_memory_nodes_workflow_canvas",
        "agent_memory_nodes",
        ["workflow_id", "canvas_node_id"],
    )
    op.create_index("ix_agent_memory_nodes_workflow_id", "agent_memory_nodes", ["workflow_id"])

    op.create_table(
        "agent_memory_edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canvas_node_id", sa.String(128), nullable=False),
        sa.Column(
            "source_node_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_memory_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_memory_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(100), nullable=False),
        sa.Column("properties", JSON, nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_agent_memory_edges_workflow_canvas",
        "agent_memory_edges",
        ["workflow_id", "canvas_node_id"],
    )
    op.create_index(
        "ix_agent_memory_edges_source_node_id",
        "agent_memory_edges",
        ["source_node_id"],
    )
    op.create_index(
        "ix_agent_memory_edges_target_node_id",
        "agent_memory_edges",
        ["target_node_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("agent_memory_edges"):
        op.drop_index("ix_agent_memory_edges_target_node_id", table_name="agent_memory_edges")
        op.drop_index("ix_agent_memory_edges_source_node_id", table_name="agent_memory_edges")
        op.drop_index("ix_agent_memory_edges_workflow_canvas", table_name="agent_memory_edges")
        op.drop_table("agent_memory_edges")

    if insp.has_table("agent_memory_nodes"):
        op.drop_index("ix_agent_memory_nodes_workflow_id", table_name="agent_memory_nodes")
        op.drop_index("ix_agent_memory_nodes_workflow_canvas", table_name="agent_memory_nodes")
        op.drop_table("agent_memory_nodes")
