"""Run history encryption: the workflow setting, encrypted history rows, per-user keys

Revision ID: 161_run_history_encryption
Revises: 160_board_card_run_actor

``workflows.encrypt_run_history`` turns encryption on for runs written from then on.
An encrypted ``execution_history`` row keeps placeholders in its payload columns and the
AES-256-GCM ciphertext in ``encrypted_payload``, under the key of
``encryption_key_user_id``. ``user_history_keys`` holds one random secret per user,
Fernet-wrapped under ENCRYPTION_KEY; no API returns it.

A running execution's registry row (``active_workflow_executions``) keeps its node results
sealed in ``encrypted_node_results`` while it runs.

Existing rows and workflows read false: nothing is encrypted until a workflow turns it on.
Downgrade drops the ciphertext and the keys, so rows encrypted before it can't be read again.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "161_run_history_encryption"
down_revision: str = "160_board_card_run_actor"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Add the setting, the encrypted row columns and the key table."""
    op.add_column(
        "workflows",
        sa.Column("encrypt_run_history", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "execution_history",
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("execution_history", sa.Column("encrypted_payload", sa.Text(), nullable=True))
    op.add_column(
        "execution_history",
        sa.Column("encryption_key_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "active_workflow_executions",
        sa.Column("encrypted_node_results", sa.Text(), nullable=True),
    )
    op.create_table(
        "user_history_keys",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("wrapped_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
    )


def downgrade() -> None:
    """Drop the key table and the columns; encrypted rows keep only their placeholders."""
    op.drop_table("user_history_keys")
    op.drop_column("active_workflow_executions", "encrypted_node_results")
    op.drop_column("execution_history", "encryption_key_user_id")
    op.drop_column("execution_history", "encrypted_payload")
    op.drop_column("execution_history", "encrypted")
    op.drop_column("workflows", "encrypt_run_history")
