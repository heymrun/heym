"""The numbers behind the Analytics tab, the dashboard chat's analytics tool and Heym Work.

Reads select explicit columns and the module imports no settings, so Heym Work can run it
under its read-only database role and show exactly what Heym shows. The snapshot writer
stays in ``app.api.analytics``: Work never writes.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionHistory, Workflow, WorkflowAnalyticsSnapshot

_ORPHAN_SNAPSHOT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
BUCKET_SIZES = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}
_SNAPSHOT_COLUMNS = (
    WorkflowAnalyticsSnapshot.workflow_id,
    WorkflowAnalyticsSnapshot.workflow_name_snapshot,
    WorkflowAnalyticsSnapshot.bucket_start,
    WorkflowAnalyticsSnapshot.total_executions,
    WorkflowAnalyticsSnapshot.success_count,
    WorkflowAnalyticsSnapshot.error_count,
    WorkflowAnalyticsSnapshot.latency_sample_count,
    WorkflowAnalyticsSnapshot.total_latency_ms,
    WorkflowAnalyticsSnapshot.max_latency_ms,
)
_HISTORY_COLUMNS = (
    ExecutionHistory.workflow_id,
    ExecutionHistory.started_at,
    ExecutionHistory.status,
    ExecutionHistory.execution_time_ms,
)


@dataclass(frozen=True)
class AnalyticsStats:
    """Headline numbers for one window; field names match ``AnalyticsStatsResponse``."""

    total_executions: int = 0
    success_count: int = 0
    error_count: int = 0
    success_rate: float = 0.0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    total_executions_24h: int = 0
    success_count_24h: int = 0
    error_count_24h: int = 0
    avg_latency_24h_ms: float = 0.0
    time_saved_minutes: float = 0.0


@dataclass(frozen=True)
class MetricsSeries:
    """Per-bucket series; field names match ``TimeSeriesMetricsResponse``."""

    time_buckets: list[str] = field(default_factory=list)
    executions: list[int] = field(default_factory=list)
    successes: list[int] = field(default_factory=list)
    errors: list[int] = field(default_factory=list)
    avg_latency_ms: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowBreakdownRow:
    """One workflow's totals; field names match ``WorkflowBreakdownItem``."""

    workflow_id: uuid.UUID
    workflow_name: str
    execution_count: int
    success_count: int
    error_count: int
    success_rate: float
    error_rate: float
    avg_latency_ms: float
    time_saved_minutes: float | None


def calculate_percentile(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile of ``values``; 0.0 for an empty list."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    if index >= len(sorted_values):
        index = len(sorted_values) - 1
    return sorted_values[index]


def time_saved_minutes_for_runs(
    success_count: int,
    minutes_saved_per_run: float | None,
) -> float | None:
    """Summed minutes for one workflow, or None when no per-run estimate is set."""
    if minutes_saved_per_run is None or minutes_saved_per_run <= 0:
        return None
    return float(minutes_saved_per_run) * success_count


def compute_time_saved_minutes(
    success_by_workflow: dict[uuid.UUID | None, int],
    rate_by_workflow: dict[uuid.UUID, float],
) -> float:
    """Σ (minutes_saved_per_run × successful runs) over workflows with a known rate."""
    total = 0.0
    for wid, success_count in success_by_workflow.items():
        if wid is None:
            continue
        saved = time_saved_minutes_for_runs(success_count, rate_by_workflow.get(wid))
        if saved:
            total += saved
    return total


def normalize_bucket_start(dt: datetime) -> datetime:
    """The UTC hour an execution is counted in."""
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.replace(minute=0, second=0, microsecond=0)


def bucket_by_size(dt: datetime, bucket_delta: timedelta) -> datetime:
    """Start of the 1-hour, 6-hour or 1-day bucket ``dt`` falls in, in UTC."""
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if bucket_delta == timedelta(hours=1):
        return dt_utc.replace(minute=0, second=0, microsecond=0)
    if bucket_delta == timedelta(hours=6):
        hour = (dt_utc.hour // 6) * 6
        return dt_utc.replace(hour=hour, minute=0, second=0, microsecond=0)
    if bucket_delta == timedelta(days=1):
        return dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt_utc.replace(minute=0, second=0, microsecond=0)


def time_range_start(time_range: str, *, now: datetime | None = None) -> datetime:
    """Start of a named window (24h, 7d, 30d, all); unknown names mean 7d."""
    current_time = now or datetime.now(timezone.utc)
    time_ranges = {
        "24h": current_time - timedelta(hours=24),
        "7d": current_time - timedelta(days=7),
        "30d": current_time - timedelta(days=30),
        "all": datetime.min.replace(tzinfo=timezone.utc),
    }
    return time_ranges.get(time_range, time_ranges["7d"])


def normalize_window_bound(dt: datetime) -> datetime:
    """A window bound in UTC; naive values are taken as UTC."""
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_time_window(
    time_range: str,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[datetime, datetime]:
    """The half-open window to report on. Raises ValueError for a partial or inverted range."""
    now = datetime.now(timezone.utc)
    if start_at is None and end_at is None:
        return time_range_start(time_range, now=now), now
    if start_at is None or end_at is None:
        raise ValueError("Both start_at and end_at must be provided together")

    resolved_start = normalize_window_bound(start_at)
    resolved_end = normalize_window_bound(end_at)
    if resolved_end <= resolved_start:
        raise ValueError("end_at must be after start_at")
    return resolved_start, resolved_end


def default_bucket_delta_for_window(start_at: datetime, end_at: datetime) -> timedelta:
    """Hourly up to two days, 6-hourly up to two weeks, daily beyond."""
    duration = end_at - start_at
    if duration <= timedelta(days=2):
        return timedelta(hours=1)
    if duration <= timedelta(days=14):
        return timedelta(hours=6)
    return timedelta(days=1)


def synthetic_workflow_id_for_orphan_snapshot(workflow_name_snapshot: str) -> uuid.UUID:
    """Stable UUID for analytics rows where workflow_id was cleared (e.g. FK SET NULL)."""
    label = workflow_name_snapshot.strip() if workflow_name_snapshot else "Untitled workflow"
    return uuid.uuid5(_ORPHAN_SNAPSHOT_NAMESPACE, label)


def snapshot_scope_filter(
    *,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
) -> object:
    """Snapshots of accessible workflows plus the user's own rows whose workflow is gone."""
    return or_(
        WorkflowAnalyticsSnapshot.workflow_id.in_(accessible_workflow_ids),
        and_(
            WorkflowAnalyticsSnapshot.owner_id == user_id,
            WorkflowAnalyticsSnapshot.workflow_id.is_(None),
        ),
    )


async def _percentiles_from_history(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID | None,
    start_at: datetime,
    end_at: datetime,
    accessible_workflow_ids: list[uuid.UUID],
) -> tuple[float, float, float]:
    query_filter = ExecutionHistory.workflow_id.in_(accessible_workflow_ids)
    if workflow_id is not None:
        query_filter = ExecutionHistory.workflow_id == workflow_id

    result = await db.execute(
        select(ExecutionHistory.execution_time_ms).where(
            query_filter,
            ExecutionHistory.started_at >= start_at,
            ExecutionHistory.started_at < end_at,
            ExecutionHistory.execution_time_ms > 0,
        )
    )
    latencies = [row[0] for row in result.all()]
    return (
        calculate_percentile(latencies, 50),
        calculate_percentile(latencies, 95),
        calculate_percentile(latencies, 99),
    )


async def _stats_from_history(
    db: AsyncSession,
    *,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    start_at: datetime,
    end_at: datetime,
) -> AnalyticsStats:
    query_filter = ExecutionHistory.workflow_id.in_(accessible_workflow_ids)
    if workflow_id is not None:
        query_filter = ExecutionHistory.workflow_id == workflow_id

    since_24h = max(start_at, end_at - timedelta(hours=24))
    all_executions = (
        await db.execute(
            select(*_HISTORY_COLUMNS).where(
                query_filter,
                ExecutionHistory.started_at >= start_at,
                ExecutionHistory.started_at < end_at,
            )
        )
    ).all()
    last_24h_executions = (
        await db.execute(
            select(*_HISTORY_COLUMNS).where(
                query_filter,
                ExecutionHistory.started_at >= since_24h,
                ExecutionHistory.started_at < end_at,
            )
        )
    ).all()

    total_executions = len(all_executions)
    success_count = sum(1 for e in all_executions if e.status == "success")
    error_count = sum(1 for e in all_executions if e.status == "error")
    latencies = [e.execution_time_ms for e in all_executions if e.execution_time_ms > 0]
    latencies_24h = [e.execution_time_ms for e in last_24h_executions if e.execution_time_ms > 0]
    return AnalyticsStats(
        total_executions=total_executions,
        success_count=success_count,
        error_count=error_count,
        success_rate=(success_count / total_executions * 100) if total_executions > 0 else 0.0,
        error_rate=(error_count / total_executions * 100) if total_executions > 0 else 0.0,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
        p50_latency_ms=calculate_percentile(latencies, 50),
        p95_latency_ms=calculate_percentile(latencies, 95),
        p99_latency_ms=calculate_percentile(latencies, 99),
        total_executions_24h=len(last_24h_executions),
        success_count_24h=sum(1 for e in last_24h_executions if e.status == "success"),
        error_count_24h=sum(1 for e in last_24h_executions if e.status == "error"),
        avg_latency_24h_ms=sum(latencies_24h) / len(latencies_24h) if latencies_24h else 0.0,
    )


async def compute_analytics_stats(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    time_range: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> AnalyticsStats:
    """Stats over the window; empty when nothing is accessible. ValueError for a bad range."""
    if not accessible_workflow_ids:
        return AnalyticsStats()
    if workflow_id is not None and workflow_id not in accessible_workflow_ids:
        return AnalyticsStats()

    since, resolved_end = resolve_time_window(time_range, start_at=start_at, end_at=end_at)
    since_24h = max(since, resolved_end - timedelta(hours=24))

    scope_filter = snapshot_scope_filter(
        user_id=user_id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if workflow_id is not None:
        scope_filter = WorkflowAnalyticsSnapshot.workflow_id == workflow_id

    all_rows = (
        await db.execute(
            select(*_SNAPSHOT_COLUMNS).where(
                scope_filter,
                WorkflowAnalyticsSnapshot.bucket_start >= since,
                WorkflowAnalyticsSnapshot.bucket_start < resolved_end,
            )
        )
    ).all()
    last_24h_rows = (
        await db.execute(
            select(*_SNAPSHOT_COLUMNS).where(
                scope_filter,
                WorkflowAnalyticsSnapshot.bucket_start >= since_24h,
                WorkflowAnalyticsSnapshot.bucket_start < resolved_end,
            )
        )
    ).all()

    if not all_rows and not last_24h_rows:
        return await _stats_from_history(
            db,
            accessible_workflow_ids=accessible_workflow_ids,
            workflow_id=workflow_id,
            start_at=since,
            end_at=resolved_end,
        )

    total_executions = sum(row.total_executions for row in all_rows)
    success_count = sum(row.success_count for row in all_rows)
    error_count = sum(row.error_count for row in all_rows)
    latency_sample_count = sum(row.latency_sample_count for row in all_rows)
    total_latency_ms = sum(row.total_latency_ms for row in all_rows)
    avg_latency_ms = (total_latency_ms / latency_sample_count) if latency_sample_count > 0 else 0.0

    p50_latency_ms, p95_latency_ms, p99_latency_ms = await _percentiles_from_history(
        db,
        workflow_id=workflow_id,
        start_at=since,
        end_at=resolved_end,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if (
        latency_sample_count > 0
        and p50_latency_ms == 0.0
        and p95_latency_ms == 0.0
        and p99_latency_ms == 0.0
    ):
        # History may be deleted; keep percentile cards meaningful using persisted aggregates.
        max_latency_ms = max((row.max_latency_ms for row in all_rows), default=0.0)
        p50_latency_ms = avg_latency_ms
        p95_latency_ms = max_latency_ms
        p99_latency_ms = max_latency_ms

    latency_sample_count_24h = sum(row.latency_sample_count for row in last_24h_rows)
    total_latency_ms_24h = sum(row.total_latency_ms for row in last_24h_rows)

    success_by_workflow: dict[uuid.UUID | None, int] = {}
    for row in all_rows:
        success_by_workflow[row.workflow_id] = (
            success_by_workflow.get(row.workflow_id, 0) + row.success_count
        )
    rate_by_workflow: dict[uuid.UUID, float] = {}
    rate_ids = [wid for wid in success_by_workflow if wid is not None]
    if rate_ids:
        rate_rows = await db.execute(
            select(Workflow.id, Workflow.minutes_saved_per_run).where(Workflow.id.in_(rate_ids))
        )
        for rid, rate in rate_rows.all():
            if rate:
                rate_by_workflow[rid] = float(rate)

    return AnalyticsStats(
        total_executions=total_executions,
        success_count=success_count,
        error_count=error_count,
        success_rate=(success_count / total_executions * 100) if total_executions > 0 else 0.0,
        error_rate=(error_count / total_executions * 100) if total_executions > 0 else 0.0,
        avg_latency_ms=avg_latency_ms,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        total_executions_24h=sum(row.total_executions for row in last_24h_rows),
        success_count_24h=sum(row.success_count for row in last_24h_rows),
        error_count_24h=sum(row.error_count for row in last_24h_rows),
        avg_latency_24h_ms=(
            total_latency_ms_24h / latency_sample_count_24h if latency_sample_count_24h > 0 else 0.0
        ),
        time_saved_minutes=compute_time_saved_minutes(success_by_workflow, rate_by_workflow),
    )


async def resolve_metrics_window(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    time_range: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    """The series window; "all" starts at the earliest snapshot or run, else one day back."""
    if start_at is not None or end_at is not None:
        return resolve_time_window(time_range, start_at=start_at, end_at=end_at)

    if time_range != "all":
        return resolve_time_window(time_range)

    now = datetime.now(timezone.utc)
    scope_filter = snapshot_scope_filter(
        user_id=user_id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if workflow_id is not None:
        scope_filter = WorkflowAnalyticsSnapshot.workflow_id == workflow_id

    earliest_snapshot = (
        await db.execute(
            select(func.min(WorkflowAnalyticsSnapshot.bucket_start)).where(scope_filter)
        )
    ).scalar_one_or_none()
    if earliest_snapshot is not None:
        return normalize_window_bound(earliest_snapshot), now

    history_filter = ExecutionHistory.workflow_id.in_(accessible_workflow_ids)
    if workflow_id is not None:
        history_filter = ExecutionHistory.workflow_id == workflow_id

    earliest_history = (
        await db.execute(select(func.min(ExecutionHistory.started_at)).where(history_filter))
    ).scalar_one_or_none()
    if earliest_history is not None:
        return normalize_window_bound(earliest_history), now

    return now - timedelta(days=1), now


async def compute_metrics_series(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    since: datetime,
    until: datetime,
    bucket_delta: timedelta,
) -> MetricsSeries:
    """Executions, successes, errors and average latency per bucket over ``[since, until)``."""
    scope_filter = snapshot_scope_filter(
        user_id=user_id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if workflow_id:
        scope_filter = WorkflowAnalyticsSnapshot.workflow_id == workflow_id

    rows = (
        await db.execute(
            select(*_SNAPSHOT_COLUMNS).where(
                scope_filter,
                WorkflowAnalyticsSnapshot.bucket_start >= since,
                WorkflowAnalyticsSnapshot.bucket_start < until,
            )
        )
    ).all()

    buckets: dict[str, dict] = {}
    current = bucket_by_size(since, bucket_delta)
    while current < until:
        buckets[current.isoformat()] = {
            "executions": 0,
            "successes": 0,
            "errors": 0,
            "latency_total_ms": 0.0,
            "latency_samples": 0,
        }
        current += bucket_delta

    if rows:
        for row in rows:
            bucket_key = bucket_by_size(row.bucket_start, bucket_delta).isoformat()
            if bucket_key not in buckets:
                continue
            buckets[bucket_key]["executions"] += row.total_executions
            buckets[bucket_key]["successes"] += row.success_count
            buckets[bucket_key]["errors"] += row.error_count
            if row.latency_sample_count > 0:
                buckets[bucket_key]["latency_total_ms"] += row.total_latency_ms
                buckets[bucket_key]["latency_samples"] += row.latency_sample_count
    else:
        query_filter = ExecutionHistory.workflow_id.in_(accessible_workflow_ids)
        if workflow_id:
            query_filter = ExecutionHistory.workflow_id == workflow_id
        executions = (
            await db.execute(
                select(*_HISTORY_COLUMNS).where(
                    query_filter,
                    ExecutionHistory.started_at >= since,
                    ExecutionHistory.started_at < until,
                )
            )
        ).all()
        for execution in executions:
            bucket_key = bucket_by_size(execution.started_at, bucket_delta).isoformat()
            if bucket_key not in buckets:
                continue
            buckets[bucket_key]["executions"] += 1
            if execution.status == "success":
                buckets[bucket_key]["successes"] += 1
            elif execution.status == "error":
                buckets[bucket_key]["errors"] += 1
            if execution.execution_time_ms > 0:
                buckets[bucket_key]["latency_total_ms"] += execution.execution_time_ms
                buckets[bucket_key]["latency_samples"] += 1

    ordered = sorted(buckets.items())
    return MetricsSeries(
        time_buckets=[key for key, _ in ordered],
        executions=[bucket["executions"] for _, bucket in ordered],
        successes=[bucket["successes"] for _, bucket in ordered],
        errors=[bucket["errors"] for _, bucket in ordered],
        avg_latency_ms=[
            bucket["latency_total_ms"] / bucket["latency_samples"]
            if bucket["latency_samples"] > 0
            else 0.0
            for _, bucket in ordered
        ],
    )


async def compute_workflow_breakdown(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
    since: datetime,
    until: datetime,
    limit: int,
) -> list[WorkflowBreakdownRow]:
    """Per-workflow totals, most executed first, including snapshots of deleted workflows."""
    if not accessible_workflow_ids:
        return []
    snapshot_scope = snapshot_scope_filter(
        user_id=user_id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    rows = (
        await db.execute(
            select(*_SNAPSHOT_COLUMNS).where(
                snapshot_scope,
                WorkflowAnalyticsSnapshot.bucket_start >= since,
                WorkflowAnalyticsSnapshot.bucket_start < until,
            )
        )
    ).all()

    aggregates: dict[uuid.UUID, dict[str, float]] = {}
    workflow_name_by_id: dict[uuid.UUID, str] = {}

    def _bucket(group_id: uuid.UUID) -> dict[str, float]:
        return aggregates.setdefault(
            group_id,
            {"total": 0, "success": 0, "error": 0, "latency_total_ms": 0.0, "latency_samples": 0},
        )

    if rows:
        for row in rows:
            group_id = (
                synthetic_workflow_id_for_orphan_snapshot(row.workflow_name_snapshot)
                if row.workflow_id is None
                else row.workflow_id
            )
            workflow_name_by_id.setdefault(
                group_id, row.workflow_name_snapshot or "Untitled workflow"
            )
            agg = _bucket(group_id)
            agg["total"] += row.total_executions
            agg["success"] += row.success_count
            agg["error"] += row.error_count
            agg["latency_total_ms"] += row.total_latency_ms
            agg["latency_samples"] += row.latency_sample_count
    else:
        executions = (
            await db.execute(
                select(*_HISTORY_COLUMNS).where(
                    ExecutionHistory.workflow_id.in_(accessible_workflow_ids),
                    ExecutionHistory.started_at >= since,
                    ExecutionHistory.started_at < until,
                )
            )
        ).all()
        name_rows = await db.execute(
            select(Workflow.id, Workflow.name).where(Workflow.id.in_(accessible_workflow_ids))
        )
        workflow_name_by_id = {row[0]: row[1] for row in name_rows.all()}
        for execution in executions:
            agg = _bucket(execution.workflow_id)
            agg["total"] += 1
            if execution.status == "success":
                agg["success"] += 1
            elif execution.status == "error":
                agg["error"] += 1
            if execution.execution_time_ms > 0:
                agg["latency_total_ms"] += execution.execution_time_ms
                agg["latency_samples"] += 1

    accessible_ids = set(accessible_workflow_ids)
    real_ids = [wf_id for wf_id in aggregates if wf_id in accessible_ids]
    configured_rates: dict[uuid.UUID, float | None] = {}
    if real_ids:
        rate_rows = await db.execute(
            select(Workflow.id, Workflow.minutes_saved_per_run).where(Workflow.id.in_(real_ids))
        )
        configured_rates = {rid: float(rate) if rate else None for rid, rate in rate_rows.all()}

    items: list[WorkflowBreakdownRow] = []
    for wf_id, agg in aggregates.items():
        total = int(agg["total"])
        success = int(agg["success"])
        error = int(agg["error"])
        samples = int(agg["latency_samples"])
        items.append(
            WorkflowBreakdownRow(
                workflow_id=wf_id,
                workflow_name=workflow_name_by_id.get(wf_id, "Untitled workflow"),
                execution_count=total,
                success_count=success,
                error_count=error,
                success_rate=(success / total * 100.0) if total > 0 else 0.0,
                error_rate=(error / total * 100.0) if total > 0 else 0.0,
                avg_latency_ms=float(agg["latency_total_ms"]) / samples if samples > 0 else 0.0,
                time_saved_minutes=time_saved_minutes_for_runs(
                    success, configured_rates.get(wf_id)
                ),
            )
        )
    items.sort(key=lambda item: item.execution_count, reverse=True)
    return items[:limit]
