"""add router columns to llm_traces

Revision ID: 125_llm_trace_router_cols
Revises: 124_add_model_router_cred
Create Date: 2026-09-22 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "125_llm_trace_router_cols"
down_revision: Union[str, None] = "124_add_model_router_cred"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_traces",
        sa.Column("router_credential_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("llm_traces", sa.Column("router_label", sa.String(length=255), nullable=True))
    op.create_index("ix_llm_traces_router_credential_id", "llm_traces", ["router_credential_id"])
    op.create_foreign_key(
        "fk_llm_traces_router_credential_id",
        "llm_traces",
        "credentials",
        ["router_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_llm_traces_router_credential_id", "llm_traces", type_="foreignkey")
    op.drop_index("ix_llm_traces_router_credential_id", table_name="llm_traces")
    op.drop_column("llm_traces", "router_label")
    op.drop_column("llm_traces", "router_credential_id")
