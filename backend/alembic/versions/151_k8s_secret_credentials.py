"""Credentials declared as Kubernetes Secrets: a pointer column, and per-instance sync state.

`credentials.source` holds `k8s:<namespace>/<secret-name>` for a Secret-backed row, and
the check constraint makes Postgres refuse anything but that pointer in
`encrypted_config` on such a row, whatever writes it. It also refuses a pointer on a
row without `source`, so only the watcher can make a row resolve from a Secret.

`cluster_instances.credentials_synced_at` lets dispatch skip an instance whose
processes have not synced their Secrets yet.

Revision ID: 151_k8s_secret_credentials
Revises: 150_google_meet_credential
"""

import sqlalchemy as sa

from alembic import op

revision: str = "151_k8s_secret_credentials"
down_revision: str = "150_google_meet_credential"
branch_labels: None = None
depends_on: None = None

_CHECK = (
    "(source IS NULL AND encrypted_config NOT LIKE 'k8s:%') "
    "OR (source IS NOT NULL AND encrypted_config = source)"
)


def upgrade() -> None:
    """Existing rows all hold ciphertexts and no source, so the constraint holds at once."""
    op.add_column("credentials", sa.Column("source", sa.String(length=320), nullable=True))
    op.create_check_constraint("ck_credentials_source_pointer", "credentials", _CHECK)
    op.add_column(
        "cluster_instances",
        sa.Column("credentials_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Secret-backed rows hold no value, so they are removed rather than left unreadable."""
    op.drop_column("cluster_instances", "credentials_synced_at")
    op.drop_constraint("ck_credentials_source_pointer", "credentials", type_="check")
    op.execute("DELETE FROM credentials WHERE source IS NOT NULL")
    op.drop_column("credentials", "source")
