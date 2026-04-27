"""Fix workflow_analytics_snapshots unique constraint to handle NULL columns.

PostgreSQL treats NULL != NULL in standard unique constraints, so rows with
NULL workflow_id or NULL owner_id were never deduplicated on upsert — every
sub-workflow execution created a new row instead of incrementing the counter.

Fix:
  1. Merge duplicate rows (same workflow_id/owner_id/bucket_start) by summing
     their counters into the canonical row (MIN id per group), then deleting
     the extras.  This is required before the new constraint can be built.
  2. Recreate the constraint with NULLS NOT DISTINCT (PostgreSQL 15+) so that
     two NULLs in the same column are treated as equal for uniqueness purposes.
"""

from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Step 1: Aggregate duplicate rows into the canonical row (MIN id).
    # Duplicates exist because the old constraint ignored NULL columns, causing
    # every upsert with a NULL key to INSERT a fresh row (total_executions=1)
    # rather than UPDATE the existing one.
    op.execute(
        """
        WITH grouped AS (
            SELECT
                MIN(id::text)::uuid           AS keep_id,
                workflow_id,
                owner_id,
                bucket_start,
                SUM(total_executions)         AS total_executions,
                SUM(success_count)            AS success_count,
                SUM(error_count)              AS error_count,
                SUM(latency_sample_count)     AS latency_sample_count,
                SUM(total_latency_ms)         AS total_latency_ms,
                MAX(max_latency_ms)           AS max_latency_ms,
                MAX(last_run_at)              AS last_run_at
            FROM workflow_analytics_snapshots
            GROUP BY workflow_id, owner_id, bucket_start
        )
        UPDATE workflow_analytics_snapshots w
        SET
            total_executions     = g.total_executions,
            success_count        = g.success_count,
            error_count          = g.error_count,
            latency_sample_count = g.latency_sample_count,
            total_latency_ms     = g.total_latency_ms,
            max_latency_ms       = g.max_latency_ms,
            last_run_at          = g.last_run_at
        FROM grouped g
        WHERE w.id = g.keep_id
        """
    )

    # Step 2: Delete all duplicate rows, keeping only the canonical one.
    op.execute(
        """
        DELETE FROM workflow_analytics_snapshots
        WHERE id NOT IN (
            SELECT MIN(id::text)::uuid
            FROM workflow_analytics_snapshots
            GROUP BY workflow_id, owner_id, bucket_start
        )
        """
    )

    # Step 3: Drop old constraint and recreate with NULLS NOT DISTINCT.
    op.drop_constraint(
        "uq_workflow_analytics_snapshot_scope",
        "workflow_analytics_snapshots",
        type_="unique",
    )
    op.execute(
        """
        ALTER TABLE workflow_analytics_snapshots
        ADD CONSTRAINT uq_workflow_analytics_snapshot_scope
        UNIQUE NULLS NOT DISTINCT (workflow_id, owner_id, bucket_start)
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workflow_analytics_snapshot_scope",
        "workflow_analytics_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_workflow_analytics_snapshot_scope",
        "workflow_analytics_snapshots",
        ["workflow_id", "owner_id", "bucket_start"],
    )
