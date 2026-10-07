import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    TeamMember,
    User,
    Workflow,
    WorkflowAnalyticsSnapshot,
    WorkflowTeamShare,
)
from app.db.session import get_db
from app.models.schemas import (
    AnalyticsStatsResponse,
    TimeSeriesMetricsResponse,
    WorkflowBreakdownItem,
    WorkflowBreakdownResponse,
)
from app.services import analytics_metrics
from app.services.analytics_metrics import (
    BUCKET_SIZES,
    calculate_percentile,
    compute_time_saved_minutes,
    normalize_bucket_start,
    time_saved_minutes_for_runs,
)
from app.services.analytics_metrics import (
    default_bucket_delta_for_window as _default_bucket_delta_for_window,
)
from app.services.analytics_metrics import resolve_time_window as _resolve_time_window
from app.services.workflow_access import explicit_workflow_share_ids

__all__ = [
    "calculate_percentile",
    "compute_analytics_stats",
    "compute_time_saved_minutes",
    "get_accessible_workflow_ids",
    "normalize_bucket_start",
    "resolve_execution_analytics_bucket",
    "time_saved_minutes_for_runs",
    "upsert_workflow_analytics_snapshot",
]

router = APIRouter()


async def get_accessible_workflow_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(Workflow.id).where(
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(explicit_workflow_share_ids(user_id)),
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


async def upsert_workflow_analytics_snapshot(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    workflow_name_snapshot: str,
    status: str,
    execution_time_ms: float,
    started_at: datetime | None = None,
    count_execution: bool = True,
) -> None:
    """Store metadata-only hourly analytics snapshot for UI analytics and chat analytics tools."""
    if workflow_id is None and owner_id is None:
        return

    run_at = started_at or datetime.now(timezone.utc)
    bucket_start = normalize_bucket_start(run_at)
    is_success = 1 if status == "success" else 0
    is_error = 1 if status == "error" else 0
    exec_increment = 1 if count_execution else 0
    has_latency = 1 if execution_time_ms > 0 else 0
    latency = execution_time_ms if execution_time_ms > 0 else 0.0
    latency_sample_increment = has_latency if count_execution else 0
    latency_increment = latency if count_execution else 0.0
    snapshot_name = workflow_name_snapshot or "Untitled workflow"

    stmt = insert(WorkflowAnalyticsSnapshot).values(
        workflow_id=workflow_id,
        owner_id=owner_id,
        workflow_name_snapshot=snapshot_name,
        bucket_start=bucket_start,
        total_executions=exec_increment,
        success_count=is_success,
        error_count=is_error,
        latency_sample_count=latency_sample_increment,
        total_latency_ms=latency_increment,
        max_latency_ms=latency_increment,
        last_run_at=run_at,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_workflow_analytics_snapshot_scope",
        set_={
            "workflow_name_snapshot": snapshot_name,
            "total_executions": WorkflowAnalyticsSnapshot.total_executions + exec_increment,
            "success_count": WorkflowAnalyticsSnapshot.success_count + is_success,
            "error_count": WorkflowAnalyticsSnapshot.error_count + is_error,
            "latency_sample_count": WorkflowAnalyticsSnapshot.latency_sample_count
            + latency_sample_increment,
            "total_latency_ms": WorkflowAnalyticsSnapshot.total_latency_ms + latency_increment,
            "max_latency_ms": (
                func.greatest(WorkflowAnalyticsSnapshot.max_latency_ms, latency)
                if (count_execution and latency > 0)
                else WorkflowAnalyticsSnapshot.max_latency_ms
            ),
            "last_run_at": run_at,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await db.execute(stmt)


async def resolve_execution_analytics_bucket(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    candidate_time: datetime | None = None,
    snapshot: dict | None = None,
    history_started_at: datetime | None = None,
    is_already_counted: bool = True,
) -> datetime | None:
    """Resolve the canonical, stable analytics bucket timestamp for an execution.

    For executions that were already counted at pause time, the final outcome must
    land in the EXACT bucket where the execution was originally counted, even across
    multiple approval pauses, cross-hour resumes, or DB vs app clock mismatches.

    If an already-counted execution lacks reliable bucket metadata (legacy run),
    returns None so callers preserve main's analytics behavior rather than guessing
    and potentially corrupting an existing bucket.
    """
    if not is_already_counted:
        return history_started_at or candidate_time or datetime.now(timezone.utc)

    initial_time: datetime | None = None
    has_snapshot_bucket = False
    if snapshot and isinstance(snapshot, dict):
        raw = snapshot.get("analytics_bucket_time") or snapshot.get("analytics_bucket_start")
        if raw:
            if isinstance(raw, datetime):
                initial_time = raw
                has_snapshot_bucket = True
            elif isinstance(raw, str):
                try:
                    initial_time = datetime.fromisoformat(raw)
                    has_snapshot_bucket = True
                except (ValueError, TypeError):
                    initial_time = None

    # For already-counted runs, if the snapshot lacks reliable bucket metadata,
    # the original bucket is not known. Preserve main's behavior by returning None.
    if not has_snapshot_bucket:
        return None

    if workflow_id is None:
        return initial_time

    def _to_utc(dt: datetime) -> datetime:
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    target_bucket = normalize_bucket_start(initial_time)
    t_utc = _to_utc(target_bucket)

    where_clauses = [WorkflowAnalyticsSnapshot.workflow_id == workflow_id]
    if owner_id is None:
        where_clauses.append(WorkflowAnalyticsSnapshot.owner_id.is_(None))
    else:
        where_clauses.append(WorkflowAnalyticsSnapshot.owner_id == owner_id)
    stmt = select(WorkflowAnalyticsSnapshot.bucket_start).where(*where_clauses)
    raw_buckets = (await db.execute(stmt)).scalars().all()
    bucket_map = {_to_utc(b): b for b in raw_buckets}

    if t_utc in bucket_map:
        return bucket_map[t_utc]

    return target_bucket


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
    stats = await analytics_metrics.compute_analytics_stats(
        db,
        user_id=user_id,
        accessible_workflow_ids=await get_accessible_workflow_ids(db, user_id),
        workflow_id=workflow_id,
        time_range=time_range,
        start_at=start_at,
        end_at=end_at,
    )
    return AnalyticsStatsResponse(**asdict(stats))


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
        since, resolved_end = await analytics_metrics.resolve_metrics_window(
            db,
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

    series = await analytics_metrics.compute_metrics_series(
        db,
        user_id=current_user.id,
        accessible_workflow_ids=accessible_workflow_ids,
        workflow_id=workflow_id,
        since=since,
        until=resolved_end,
        bucket_delta=BUCKET_SIZES.get(
            bucket_size, _default_bucket_delta_for_window(since, resolved_end)
        ),
    )
    return TimeSeriesMetricsResponse(**asdict(series))


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

    rows = await analytics_metrics.compute_workflow_breakdown(
        db,
        user_id=current_user.id,
        accessible_workflow_ids=accessible_workflow_ids,
        since=since,
        until=resolved_end,
        limit=limit,
    )
    return WorkflowBreakdownResponse(items=[WorkflowBreakdownItem(**asdict(row)) for row in rows])
