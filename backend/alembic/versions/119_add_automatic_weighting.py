"""add automatic weighting flag and per-instance weight_configured

Revision ID: 119_add_auto_weighting
Revises: 118_add_run_instance_attr
Create Date: 2026-08-28 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "119_add_auto_weighting"
down_revision: Union[str, None] = "118_add_run_instance_attr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # False means "never given a weight", which is what makes auto-seeding run
    # once per machine instead of fighting an operator who chose 0 on purpose.
    op.add_column(
        "cluster_instances",
        sa.Column("weight_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Existing main rows carry a deliberate 100 from their first heartbeat.
    op.execute("UPDATE cluster_instances SET weight_configured = true WHERE role = 'main'")

    op.add_column(
        "cluster_dispatch_state",
        sa.Column("automatic_weighting", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("cluster_dispatch_state", "automatic_weighting")
    op.drop_column("cluster_instances", "weight_configured")
