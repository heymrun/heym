"""add cron slot claims

Revision ID: 104_add_cron_slot_claims
Revises: 103_add_google_drive_cred_type
Create Date: 2026-08-04 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "104_add_cron_slot_claims"
down_revision: Union[str, None] = "103_add_google_drive_cred_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cron_slot_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("slot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workflow_id", "node_id", "slot_at", name="uq_cron_slot_claim"),
    )
    op.create_index("ix_cron_slot_claims_workflow_id", "cron_slot_claims", ["workflow_id"])
    op.create_index("ix_cron_slot_claims_slot_at", "cron_slot_claims", ["slot_at"])


def downgrade() -> None:
    op.drop_index("ix_cron_slot_claims_slot_at", table_name="cron_slot_claims")
    op.drop_index("ix_cron_slot_claims_workflow_id", table_name="cron_slot_claims")
    op.drop_table("cron_slot_claims")
