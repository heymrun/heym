"""add cluster_instances

Revision ID: 116_add_cluster_instances
Revises: 115_add_sso_settings
Create Date: 2026-08-27 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "116_add_cluster_instances"
down_revision: Union[str, None] = "115_add_sso_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cluster_instances",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False, server_default="worker"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.String(64), nullable=False, server_default=""),
        sa.Column("schema_revision", sa.String(64), nullable=False, server_default=""),
        sa.Column("keys_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("docker_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("db_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_cluster_instances_heartbeat_at", "cluster_instances", ["heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_cluster_instances_heartbeat_at", table_name="cluster_instances")
    op.drop_table("cluster_instances")
