"""Fix workflow_analytics_snapshots workflow_id FK to use CASCADE instead of SET NULL.

When a workflow is deleted, SET NULL causes workflow_id to become NULL. With the
NULLS NOT DISTINCT constraint added in migration 050, a second workflow deletion
for the same (owner_id, bucket_start) bucket raises a UniqueViolationError.

Fix: change ON DELETE SET NULL -> ON DELETE CASCADE so analytics snapshots are
deleted along with the workflow instead of having their workflow_id nulled out.
"""

from alembic import op

revision: str = "052"
down_revision: str | None = "051"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Drop the old FK that used SET NULL
    op.drop_constraint(
        "workflow_analytics_snapshots_workflow_id_fkey",
        "workflow_analytics_snapshots",
        type_="foreignkey",
    )
    # Recreate with CASCADE so rows are deleted with the workflow
    op.create_foreign_key(
        "workflow_analytics_snapshots_workflow_id_fkey",
        "workflow_analytics_snapshots",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "workflow_analytics_snapshots_workflow_id_fkey",
        "workflow_analytics_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "workflow_analytics_snapshots_workflow_id_fkey",
        "workflow_analytics_snapshots",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )
