import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    ExecutionHistory,
    TeamMember,
    User,
    Workflow,
    WorkflowAnalyticsSnapshot,
    WorkflowShare,
    WorkflowTeamShare,
)
from app.db.session import get_db
from app.models.schemas import (
    AnalyticsStatsResponse,
    TimeSeriesMetricsResponse,
    WorkflowBreakdownItem,
    WorkflowBreakdownResponse,
)

router = APIRouter()


async def get_accessible_workflow_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(Workflow.id).where(
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)
                ),
                Workflow.id.in_(
                    select(WorkflowTeamShare.workflow_id).where(
                        WorkflowTeamShare.team_id.in_(
                            select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                        )
                    )
                ),
            )
        )
    )
    return [row[0] for row in result.all()]


def _empty_analytics_stats() -> AnalyticsStatsResponse:
    return AnalyticsStatsResponse(
        total_executions=0,
        success_count=0,
        error_count=0,
        success_rate=0.0,
        error_rate=0.0,
        avg_latency_ms=0.0,
        p50_latency_ms=0.0,
        p95_latency_ms=0.0,
        p99_latency_ms=0.0,
        total_executions_24h=0,
        success_count_24h=0,
        error_count_24h=0,
        avg_latency_24h_ms=0.0,
    )


def calculate_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    if index >= len(sorted_values):
        index = len(sorted_values) - 1
    return sorted_values[index]


def normalize_bucket_start(dt: datetime) -> datetime:
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.replace(minute=0, second=0, microsecond=0)


async def upsert_workflow_analytics_snapshot(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    workflow_name_snapshot: str,
    status: str,
    execution_time_ms: float,
    started_at: datetime | None = None,
) -> None:
    """Store metadata-only hourly analytics snapshot for UI analytics and chat analytics tools."""
    if workflow_id is None and owner_id is None:
        return

    run_at = started_at or datetime.now(timezone.utc)
    bucket_start = normalize_bucket_start(run_at)
    is_success = 1 if status == "success" else 0
    is_error = 1 if status == "error" else 0
    has_latency = 1 if execution_time_ms > 0 else 0
    latency = execution_time_ms if execution_time_ms > 0 else 0.0
    snapshot_name = workflow_name_snapshot or "Untitled workflow"

    stmt = insert(WorkflowAnalyticsSnapshot).values(
        workflow_id=workflow_id,
        owner_id=owner_id,
        workflow_name_snapshot=snapshot_name,
        bucket_start=bucket_start,
        total_executions=1,
        success_count=is_success,
        error_count=is_error,
        latency_sample_count=has_latency,
        total_latency_ms=latency,
        max_latency_ms=latency,
        last_run_at=run_at,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_workflow_analytics_snapshot_scope",
        set_={
            "workflow_name_snapshot": snapshot_name,
            "total_executions": WorkflowAnalyticsSnapshot.total_executions + 1,
            "success_count": WorkflowAnalyticsSnapshot.success_count + is_success,
            "error_count": WorkflowAnalyticsSnapshot.error_count + is_error,
            "latency_sample_count": WorkflowAnalyticsSnapshot.latency_sample_count + has_latency,
            "total_latency_ms": WorkflowAnalyticsSnapshot.total_latency_ms + latency,
            "max_latency_ms": WorkflowAnalyticsSnapshot.max_latency_ms
            if latency <= 0
            else func.greatest(WorkflowAnalyticsSnapshot.max_latency_ms, latency),
            "last_run_at": run_at,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await db.execute(stmt)


def _bucket_by_size(dt: datetime, bucket_delta: timedelta) -> datetime:
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if bucket_delta == timedelta(hours=1):
        return dt_utc.replace(minute=0, second=0, microsecond=0)
    if bucket_delta == timedelta(hours=6):
        hour = (dt_utc.hour // 6) * 6
        return dt_utc.replace(hour=hour, minute=0, second=0, microsecond=0)
    if bucket_delta == timedelta(days=1):
        return dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt_utc.replace(minute=0, second=0, microsecond=0)


def _time_range_start(time_range: str, *, now: datetime | None = None) -> datetime:
    current_time = now or datetime.now(timezone.utc)
    time_ranges = {
        "24h": current_time - timedelta(hours=24),
        "7d": current_time - timedelta(days=7),
        "30d": current_time - timedelta(days=30),
        "all": datetime.min.replace(tzinfo=timezone.utc),
    }
    return time_ranges.get(time_range, time_ranges["7d"])


def _normalize_window_bound(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _resolve_time_window(
    time_range: str,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if start_at is None and end_at is None:
        return _time_range_start(time_range, now=now), now
    if start_at is None or end_at is None:
        raise ValueError("Both start_at and end_at must be provided together")

    resolved_start = _normalize_window_bound(start_at)
    resolved_end = _normalize_window_bound(end_at)
    if resolved_end <= resolved_start:
        raise ValueError("end_at must be after start_at")
    return resolved_start, resolved_end


def _default_bucket_delta_for_window(start_at: datetime, end_at: datetime) -> timedelta:
    duration = end_at - start_at
    if duration <= timedelta(days=2):
        return timedelta(hours=1)
    if duration <= timedelta(days=14):
        return timedelta(hours=6)
    return timedelta(days=1)


def _build_snapshot_scope_filter(
    *,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
) -> object:
    return or_(
        WorkflowAnalyticsSnapshot.workflow_id.in_(accessible_workflow_ids),
        and_(
            WorkflowAnalyticsSnapshot.owner_id == user_id,
            WorkflowAnalyticsSnapshot.workflow_id.is_(None),
        ),
    )


_ANALYTICS_ORPHAN_SNAPSHOT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _synthetic_workflow_id_for_orphan_snapshot(workflow_name_snapshot: str) -> uuid.UUID:
    """Stable UUID for analytics rows where workflow_id was cleared (e.g. FK SET NULL)."""
    label = workflow_name_snapshot.strip() if workflow_name_snapshot else "Untitled workflow"
    return uuid.uuid5(_ANALYTICS_ORPHAN_SNAPSHOT_NAMESPACE, label)


async def _compute_percentiles_from_history(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    workflow_id: Optional[uuid.UUID],
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


async def _compute_stats_from_history(
    db: AsyncSession,
    *,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: Optional[uuid.UUID],
    start_at: datetime,
    end_at: datetime,
) -> AnalyticsStatsResponse:
    query_filter = ExecutionHistory.workflow_id.in_(accessible_workflow_ids)
    if workflow_id is not None:
        query_filter = ExecutionHistory.workflow_id == workflow_id

    since_24h = max(start_at, end_at - timedelta(hours=24))

    all_result = await db.execute(
        select(ExecutionHistory).where(
            query_filter,
            ExecutionHistory.started_at >= start_at,
            ExecutionHistory.started_at < end_at,
        )
    )
    all_executions = all_result.scalars().all()
    last_24h_result = await db.execute(
        select(ExecutionHistory).where(
            query_filter,
            ExecutionHistory.started_at >= since_24h,
            ExecutionHistory.started_at < end_at,
        )
    )
    last_24h_executions = last_24h_result.scalars().all()

    total_executions = len(all_executions)
    success_count = sum(1 for e in all_executions if e.status == "success")
    error_count = sum(1 for e in all_executions if e.status == "error")
    success_rate = (success_count / total_executions * 100) if total_executions > 0 else 0.0
    error_rate = (error_count / total_executions * 100) if total_executions > 0 else 0.0

    latencies = [e.execution_time_ms for e in all_executions if e.execution_time_ms > 0]
    avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0
    p50_latency_ms = calculate_percentile(latencies, 50)
    p95_latency_ms = calculate_percentile(latencies, 95)
    p99_latency_ms = calculate_percentile(latencies, 99)

    total_executions_24h = len(last_24h_executions)
    success_count_24h = sum(1 for e in last_24h_executions if e.status == "success")
    error_count_24h = sum(1 for e in last_24h_executions if e.status == "error")
    latencies_24h = [e.execution_time_ms for e in last_24h_executions if e.execution_time_ms > 0]
    avg_latency_24h_ms = sum(latencies_24h) / len(latencies_24h) if latencies_24h else 0.0

    return AnalyticsStatsResponse(
        total_executions=total_executions,
        success_count=success_count,
        error_count=error_count,
        success_rate=success_rate,
        error_rate=error_rate,
        avg_latency_ms=avg_latency_ms,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        total_executions_24h=total_executions_24h,
        success_count_24h=success_count_24h,
        error_count_24h=error_count_24h,
        avg_latency_24h_ms=avg_latency_24h_ms,
    )


async def compute_analytics_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    workflow_id: Optional[uuid.UUID],
    time_range: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> AnalyticsStatsResponse:
    """
    Compute analytics stats for the given user and optional workflow.
    Used by both the analytics API and the dashboard chat tool.
    Returns empty stats if the user has no workflows or if workflow_id is not accessible.
    """
    accessible_workflow_ids = await get_accessible_workflow_ids(db, user_id)

    if not accessible_workflow_ids:
        return _empty_analytics_stats()

    if workflow_id is not None and workflow_id not in accessible_workflow_ids:
        return _empty_analytics_stats()

    since, resolved_end = _resolve_time_window(time_range, start_at=start_at, end_at=end_at)
    since_24h = max(since, resolved_end - timedelta(hours=24))

    scope_filter = _build_snapshot_scope_filter(
        user_id=user_id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if workflow_id is not None:
        scope_filter = WorkflowAnalyticsSnapshot.workflow_id == workflow_id

    all_rows_result = await db.execute(
        select(WorkflowAnalyticsSnapshot).where(
            scope_filter,
            WorkflowAnalyticsSnapshot.bucket_start >= since,
            WorkflowAnalyticsSnapshot.bucket_start < resolved_end,
        )
    )
    all_rows = all_rows_result.scalars().all()

    last_24h_rows_result = await db.execute(
        select(WorkflowAnalyticsSnapshot).where(
            scope_filter,
            WorkflowAnalyticsSnapshot.bucket_start >= since_24h,
            WorkflowAnalyticsSnapshot.bucket_start < resolved_end,
        )
    )
    last_24h_rows = last_24h_rows_result.scalars().all()

    if not all_rows and not last_24h_rows:
        return await _compute_stats_from_history(
            db,
            accessible_workflow_ids=accessible_workflow_ids,
            workflow_id=workflow_id,
            start_at=since,
            end_at=resolved_end,
        )

    total_executions = sum(row.total_executions for row in all_rows)
    success_count = sum(row.success_count for row in all_rows)
    error_count = sum(row.error_count for row in all_rows)
    success_rate = (success_count / total_executions * 100) if total_executions > 0 else 0.0
    error_rate = (error_count / total_executions * 100) if total_executions > 0 else 0.0

    latency_sample_count = sum(row.latency_sample_count for row in all_rows)
    total_latency_ms = sum(row.total_latency_ms for row in all_rows)
    avg_latency_ms = (total_latency_ms / latency_sample_count) if latency_sample_count > 0 else 0.0

    p50_latency_ms, p95_latency_ms, p99_latency_ms = await _compute_percentiles_from_history(
        db,
        user_id=user_id,
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

    total_executions_24h = sum(row.total_executions for row in last_24h_rows)
    success_count_24h = sum(row.success_count for row in last_24h_rows)
    error_count_24h = sum(row.error_count for row in last_24h_rows)
    latency_sample_count_24h = sum(row.latency_sample_count for row in last_24h_rows)
    total_latency_ms_24h = sum(row.total_latency_ms for row in last_24h_rows)
    avg_latency_24h_ms = (
        total_latency_ms_24h / latency_sample_count_24h if latency_sample_count_24h > 0 else 0.0
    )

    return AnalyticsStatsResponse(
        total_executions=total_executions,
        success_count=success_count,
        error_count=error_count,
        success_rate=success_rate,
        error_rate=error_rate,
        avg_latency_ms=avg_latency_ms,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        total_executions_24h=total_executions_24h,
        success_count_24h=success_count_24h,
        error_count_24h=error_count_24h,
        avg_latency_24h_ms=avg_latency_24h_ms,
    )


@router.get("/stats", response_model=AnalyticsStatsResponse)
async def get_analytics_stats(
    workflow_id: Optional[uuid.UUID] = Query(None, description="Filter by workflow ID"),
    time_range: str = Query("7d", description="Time range: 24h, 7d, 30d, all"),
    start_at: datetime | None = Query(None, description="Custom range start in ISO 8601"),
    end_at: datetime | None = Query(None, description="Custom range end in ISO 8601"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsStatsResponse:
    if workflow_id is not None:
        accessible = await get_accessible_workflow_ids(db, current_user.id)
        if workflow_id not in accessible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workflow not accessible",
            )
    try:
        return await compute_analytics_stats(
            db,
            current_user.id,
            workflow_id,
            time_range,
            start_at=start_at,
            end_at=end_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/stats/{workflow_id}", response_model=AnalyticsStatsResponse)
async def get_workflow_analytics_stats(
    workflow_id: uuid.UUID,
    time_range: str = Query("7d", description="Time range: 24h, 7d, 30d, all"),
    start_at: datetime | None = Query(None, description="Custom range start in ISO 8601"),
    end_at: datetime | None = Query(None, description="Custom range end in ISO 8601"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsStatsResponse:
    accessible = await get_accessible_workflow_ids(db, current_user.id)
    if workflow_id not in accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workflow not accessible",
        )
    try:
        return await compute_analytics_stats(
            db,
            current_user.id,
            workflow_id,
            time_range,
            start_at=start_at,
            end_at=end_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


async def _resolve_metrics_window(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    time_range: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    if start_at is not None or end_at is not None:
        return _resolve_time_window(time_range, start_at=start_at, end_at=end_at)

    if time_range != "all":
        return _resolve_time_window(time_range)

    now = datetime.now(timezone.utc)
    scope_filter = _build_snapshot_scope_filter(
        user_id=user_id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if workflow_id is not None:
        scope_filter = WorkflowAnalyticsSnapshot.workflow_id == workflow_id

    earliest_snapshot_result = await db.execute(
        select(func.min(WorkflowAnalyticsSnapshot.bucket_start)).where(scope_filter)
    )
    earliest_snapshot = earliest_snapshot_result.scalar_one_or_none()
    if earliest_snapshot is not None:
        return _normalize_window_bound(earliest_snapshot), now

    history_filter = ExecutionHistory.workflow_id.in_(accessible_workflow_ids)
    if workflow_id is not None:
        history_filter = ExecutionHistory.workflow_id == workflow_id

    earliest_history_result = await db.execute(
        select(func.min(ExecutionHistory.started_at)).where(history_filter)
    )
    earliest_history = earliest_history_result.scalar_one_or_none()
    if earliest_history is not None:
        return _normalize_window_bound(earliest_history), now

    return now - timedelta(days=1), now


@router.get("/metrics", response_model=TimeSeriesMetricsResponse)
async def get_analytics_metrics(
    workflow_id: Optional[uuid.UUID] = Query(None, description="Filter by workflow ID"),
    time_range: str = Query("7d", description="Time range: 24h, 7d, 30d, all"),
    bucket_size: str = Query("1h", description="Bucket size: 1h, 6h, 1d"),
    start_at: datetime | None = Query(None, description="Custom range start in ISO 8601"),
    end_at: datetime | None = Query(None, description="Custom range end in ISO 8601"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TimeSeriesMetricsResponse:
    accessible_workflow_ids = await get_accessible_workflow_ids(db, current_user.id)

    if not accessible_workflow_ids:
        return TimeSeriesMetricsResponse(
            time_buckets=[],
            executions=[],
            successes=[],
            errors=[],
            avg_latency_ms=[],
        )

    if workflow_id:
        if workflow_id not in accessible_workflow_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workflow not accessible",
            )

    try:
        since, resolved_end = await _resolve_metrics_window(
            db=db,
            user_id=current_user.id,
            accessible_workflow_ids=accessible_workflow_ids,
            workflow_id=workflow_id,
            time_range=time_range,
            start_at=start_at,
            end_at=end_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    bucket_sizes = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "1d": timedelta(days=1),
    }
    bucket_delta = bucket_sizes.get(
        bucket_size, _default_bucket_delta_for_window(since, resolved_end)
    )

    scope_filter = _build_snapshot_scope_filter(
        user_id=current_user.id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    if workflow_id:
        scope_filter = WorkflowAnalyticsSnapshot.workflow_id == workflow_id

    rows_result = await db.execute(
        select(WorkflowAnalyticsSnapshot).where(
            scope_filter,
            WorkflowAnalyticsSnapshot.bucket_start >= since,
            WorkflowAnalyticsSnapshot.bucket_start < resolved_end,
        )
    )
    rows = rows_result.scalars().all()

    buckets: dict[str, dict] = {}
    if bucket_delta == timedelta(hours=1):
        bucket_start = since.replace(minute=0, second=0, microsecond=0)
    elif bucket_delta == timedelta(hours=6):
        hour = (since.hour // 6) * 6
        bucket_start = since.replace(hour=hour, minute=0, second=0, microsecond=0)
    elif bucket_delta == timedelta(days=1):
        bucket_start = since.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        bucket_start = since.replace(minute=0, second=0, microsecond=0)

    current = bucket_start
    while current < resolved_end:
        bucket_key = current.isoformat()
        buckets[bucket_key] = {
            "executions": 0,
            "successes": 0,
            "errors": 0,
            "latency_total_ms": 0.0,
            "latency_samples": 0,
        }
        current += bucket_delta

    if rows:
        for row in rows:
            bucket_time = _bucket_by_size(row.bucket_start, bucket_delta)
            bucket_key = bucket_time.isoformat()
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
        fallback_result = await db.execute(
            select(ExecutionHistory).where(
                query_filter,
                ExecutionHistory.started_at >= since,
                ExecutionHistory.started_at < resolved_end,
            )
        )
        executions = fallback_result.scalars().all()
        for execution in executions:
            bucket_time = _bucket_by_size(execution.started_at, bucket_delta)
            bucket_key = bucket_time.isoformat()
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

    sorted_buckets = sorted(buckets.items())
    time_buckets = [bucket[0] for bucket in sorted_buckets]
    executions_list = [bucket[1]["executions"] for bucket in sorted_buckets]
    successes_list = [bucket[1]["successes"] for bucket in sorted_buckets]
    errors_list = [bucket[1]["errors"] for bucket in sorted_buckets]
    avg_latency_list = [
        (
            bucket[1]["latency_total_ms"] / bucket[1]["latency_samples"]
            if bucket[1]["latency_samples"] > 0
            else 0.0
        )
        for bucket in sorted_buckets
    ]

    return TimeSeriesMetricsResponse(
        time_buckets=time_buckets,
        executions=executions_list,
        successes=successes_list,
        errors=errors_list,
        avg_latency_ms=avg_latency_list,
    )


@router.get("/metrics/{workflow_id}", response_model=TimeSeriesMetricsResponse)
async def get_workflow_analytics_metrics(
    workflow_id: uuid.UUID,
    time_range: str = Query("7d", description="Time range: 24h, 7d, 30d, all"),
    bucket_size: str = Query("1h", description="Bucket size: 1h, 6h, 1d"),
    start_at: datetime | None = Query(None, description="Custom range start in ISO 8601"),
    end_at: datetime | None = Query(None, description="Custom range end in ISO 8601"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TimeSeriesMetricsResponse:
    return await get_analytics_metrics(
        workflow_id=workflow_id,
        time_range=time_range,
        bucket_size=bucket_size,
        start_at=start_at,
        end_at=end_at,
        current_user=current_user,
        db=db,
    )


@router.get("/workflows", response_model=WorkflowBreakdownResponse)
async def get_workflow_breakdown(
    time_range: str = Query("7d", description="Time range: 24h, 7d, 30d, all"),
    start_at: datetime | None = Query(None, description="Custom range start in ISO 8601"),
    end_at: datetime | None = Query(None, description="Custom range end in ISO 8601"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of workflows to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowBreakdownResponse:
    """
    Per-workflow execution breakdown for the current user.
    Includes snapshot rows whose workflow link was cleared (e.g. after workflow delete)
    so totals match aggregate analytics. Used for \"Most used\" and \"Most failed\" tables.
    """
    accessible_workflow_ids = await get_accessible_workflow_ids(db, current_user.id)
    if not accessible_workflow_ids:
        return WorkflowBreakdownResponse()

    try:
        since, resolved_end = _resolve_time_window(time_range, start_at=start_at, end_at=end_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    snapshot_scope = _build_snapshot_scope_filter(
        user_id=current_user.id,
        accessible_workflow_ids=accessible_workflow_ids,
    )
    rows_result = await db.execute(
        select(WorkflowAnalyticsSnapshot).where(
            snapshot_scope,
            WorkflowAnalyticsSnapshot.bucket_start >= since,
            WorkflowAnalyticsSnapshot.bucket_start < resolved_end,
        )
    )
    rows = rows_result.scalars().all()

    aggregates: dict[uuid.UUID, dict[str, float | int]] = {}
    workflow_name_by_id: dict[uuid.UUID, str] = {}
    if rows:
        for row in rows:
            wf_id = row.workflow_id
            group_id = (
                _synthetic_workflow_id_for_orphan_snapshot(row.workflow_name_snapshot)
                if wf_id is None
                else wf_id
            )
            if group_id not in aggregates:
                aggregates[group_id] = {
                    "total": 0,
                    "success": 0,
                    "error": 0,
                    "latency_total_ms": 0.0,
                    "latency_samples": 0,
                }
            if group_id not in workflow_name_by_id:
                workflow_name_by_id[group_id] = row.workflow_name_snapshot or "Untitled workflow"
            agg = aggregates[group_id]
            agg["total"] = int(agg["total"]) + row.total_executions  # type: ignore[assignment]
            agg["success"] = int(agg["success"]) + row.success_count  # type: ignore[assignment]
            agg["error"] = int(agg["error"]) + row.error_count  # type: ignore[assignment]
            agg["latency_total_ms"] = float(agg["latency_total_ms"]) + row.total_latency_ms  # type: ignore[assignment]
            agg["latency_samples"] = int(agg["latency_samples"]) + row.latency_sample_count  # type: ignore[assignment]
    else:
        fallback_result = await db.execute(
            select(ExecutionHistory).where(
                ExecutionHistory.workflow_id.in_(accessible_workflow_ids),
                ExecutionHistory.started_at >= since,
                ExecutionHistory.started_at < resolved_end,
            )
        )
        executions = fallback_result.scalars().all()
        workflow_rows = await db.execute(
            select(Workflow.id, Workflow.name).where(Workflow.id.in_(accessible_workflow_ids))
        )
        workflow_name_by_id = {row[0]: row[1] for row in workflow_rows.all()}
        for execution in executions:
            wf_id = execution.workflow_id
            if wf_id not in aggregates:
                aggregates[wf_id] = {
                    "total": 0,
                    "success": 0,
                    "error": 0,
                    "latency_total_ms": 0.0,
                    "latency_samples": 0,
                }
            agg = aggregates[wf_id]
            agg["total"] = int(agg["total"]) + 1  # type: ignore[assignment]
            if execution.status == "success":
                agg["success"] = int(agg["success"]) + 1  # type: ignore[assignment]
            elif execution.status == "error":
                agg["error"] = int(agg["error"]) + 1  # type: ignore[assignment]
            if execution.execution_time_ms > 0:
                agg["latency_total_ms"] = (
                    float(agg["latency_total_ms"]) + execution.execution_time_ms
                )  # type: ignore[assignment]
                agg["latency_samples"] = int(agg["latency_samples"]) + 1  # type: ignore[assignment]

    items: list[WorkflowBreakdownItem] = []
    for wf_id, agg in aggregates.items():
        total = int(agg["total"])  # type: ignore[assignment]
        success = int(agg["success"])  # type: ignore[assignment]
        error = int(agg["error"])  # type: ignore[assignment]
        latency_total_ms = float(agg["latency_total_ms"])  # type: ignore[assignment]
        latency_samples = int(agg["latency_samples"])  # type: ignore[assignment]
        avg_latency = latency_total_ms / latency_samples if latency_samples > 0 else 0.0
        success_rate = (success / total * 100.0) if total > 0 else 0.0
        error_rate = (error / total * 100.0) if total > 0 else 0.0
        workflow_name = workflow_name_by_id.get(wf_id, "Untitled workflow")

        items.append(
            WorkflowBreakdownItem(
                workflow_id=wf_id,
                workflow_name=workflow_name,
                execution_count=total,
                success_count=success,
                error_count=error,
                success_rate=success_rate,
                error_rate=error_rate,
                avg_latency_ms=avg_latency,
            )
        )

    # Sort by execution count descending; caller can derive \"most failed\" by error_count
    items.sort(key=lambda i: i.execution_count, reverse=True)
    return WorkflowBreakdownResponse(items=items[:limit])
