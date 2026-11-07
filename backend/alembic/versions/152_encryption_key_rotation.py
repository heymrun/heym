"""Online rotation of ENCRYPTION_KEY: the canary, rotation progress, and each instance's keys.

`encryption_canary` holds one value encrypted with this database's key, so
`python -m app.key_check` can refuse a process whose keys can't read it.
`key_rotations` keeps re-encryption progress in the database, where it survives a
leader change, and records the keys a completed rotation retired.
`cluster_instances.decrypt_fingerprints` lists the keys each instance can decrypt
with, which the compatibility rule compares while two keys are live.

Revision ID: 152_encryption_key_rotation
Revises: 151_k8s_secret_credentials
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "152_encryption_key_rotation"
down_revision: str = "151_k8s_secret_credentials"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "cluster_instances",
        sa.Column(
            "decrypt_fingerprints",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_table(
        "encryption_canary",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "key_rotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("target_fingerprint", sa.String(length=32), nullable=False),
        sa.Column(
            "retired_fingerprints",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "started_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remaining", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unreadable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_key_rotations_one_active",
        "key_rotations",
        ["active"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("ix_key_rotations_one_active", table_name="key_rotations")
    op.drop_table("key_rotations")
    op.drop_table("encryption_canary")
    op.drop_column("cluster_instances", "decrypt_fingerprints")
