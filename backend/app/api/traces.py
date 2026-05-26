import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, case, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Credential, LLMTrace, User, Workflow
from app.db.session import get_db
from app.models.schemas import (
    LLMTraceDetailResponse,
    LLMTraceListItem,
    LLMTraceListResponse,
    TraceStatsByModel,
    TraceStatsByTime,
    TraceStatsKpis,
    TraceStatsRangeMeta,
    TraceStatsResponse,
)
from app.services.llm_pricing import resolve_costs_for_user
from app.services.llm_pricing_sync import ensure_pricing_synced

router = APIRouter()


_RANGE_TABLE: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 300),
    "24h": (timedelta(hours=24), 3600),
    "7d": (timedelta(days=7), 6 * 3600),
    "30d": (timedelta(days=30), 86400),
}


def _resolve_range(
    range_key: str, *, now: datetime | None = None
) -> tuple[datetime | None, datetime, int]:
    """Returns (start_dt or None, end_dt, bucket_seconds). 'all' returns start=None.
    Unknown range_key falls back to '7d'."""
    now = now or datetime.now(timezone.utc)
    if range_key == "all":
        return (None, now, 86400)
    delta, bucket = _RANGE_TABLE.get(range_key, _RANGE_TABLE["7d"])
    return (now - delta, now, bucket)


@router.get("", response_model=LLMTraceListResponse)
async def list_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credential_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    source: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    range: str | None = Query(None, description="Optional time window: 1h|24h|7d|30d|all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMTraceListResponse:
    """List LLM traces for the current user with pagination."""
    filters = [LLMTrace.user_id == current_user.id]
    if credential_id:
        filters.append(LLMTrace.credential_id == credential_id)
    if workflow_id:
        filters.append(LLMTrace.workflow_id == workflow_id)
    if source:
        filters.append(LLMTrace.source == source)
    if status_filter == "error":
        filters.append(LLMTrace.error.is_not(None))
    elif status_filter == "success":
        filters.append(LLMTrace.error.is_(None))
    if range is not None:
        start_dt, _, _ = _resolve_range(range)
        if start_dt is not None:
            filters.append(LLMTrace.created_at >= start_dt)

    base_query = (
        select(LLMTrace, Credential.name, Workflow.name)
        .outerjoin(Credential, LLMTrace.credential_id == Credential.id)
        .outerjoin(Workflow, LLMTrace.workflow_id == Workflow.id)
        .where(*filters)
    )

    if search:
        pattern = f"%{search}%"
        base_query = base_query.where(
            or_(
                LLMTrace.model.ilike(pattern),
                LLMTrace.node_label.ilike(pattern),
                Workflow.name.ilike(pattern),
                Credential.name.ilike(pattern),
                cast(LLMTrace.request, String).ilike(pattern),
                cast(LLMTrace.response, String).ilike(pattern),
            )
        )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    order_by = LLMTrace.created_at.asc() if order == "asc" else LLMTrace.created_at.desc()
    result = await db.execute(base_query.order_by(order_by).limit(limit).offset(offset))

    items: list[LLMTraceListItem] = []
    for trace, credential_name, workflow_name in result.all():
        items.append(
            LLMTraceListItem(
                id=trace.id,
                created_at=trace.created_at,
                source=trace.source,
                request_type=trace.request_type,
                provider=trace.provider,
                model=trace.model,
                credential_id=trace.credential_id,
                credential_name=credential_name,
                workflow_id=trace.workflow_id,
                workflow_name=workflow_name,
                node_id=trace.node_id,
                node_label=trace.node_label,
                status="error" if trace.error else "success",
                elapsed_ms=trace.elapsed_ms,
                prompt_tokens=trace.prompt_tokens,
                completion_tokens=trace.completion_tokens,
                total_tokens=trace.total_tokens,
            )
        )

    return LLMTraceListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=TraceStatsResponse)
async def get_trace_stats(
    range: str = Query("7d", description="1h | 24h | 7d | 30d | all"),
    source: str | None = None,
    credential_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TraceStatsResponse:
    """Aggregate KPIs, per-model breakdown, and per-time-bucket series for the
    current user's LLM traces in the requested window."""
    await ensure_pricing_synced(db, force=False)

    start_dt, end_dt, bucket_seconds = _resolve_range(range)
    filters = [LLMTrace.user_id == current_user.id]
    if credential_id:
        filters.append(LLMTrace.credential_id == credential_id)
    if workflow_id:
        filters.append(LLMTrace.workflow_id == workflow_id)
    if source:
        filters.append(LLMTrace.source == source)
    if status_filter == "error":
        filters.append(LLMTrace.error.is_not(None))
    elif status_filter == "success":
        filters.append(LLMTrace.error.is_(None))
    if start_dt is not None:
        filters.append(LLMTrace.created_at >= start_dt)

    def _apply_search(stmt):
        if not search:
            return stmt
        pattern = f"%{search}%"
        return (
            stmt.outerjoin(Workflow, LLMTrace.workflow_id == Workflow.id)
            .outerjoin(Credential, LLMTrace.credential_id == Credential.id)
            .where(
                or_(
                    LLMTrace.model.ilike(pattern),
                    LLMTrace.node_label.ilike(pattern),
                    Workflow.name.ilike(pattern),
                    Credential.name.ilike(pattern),
                    cast(LLMTrace.request, String).ilike(pattern),
                    cast(LLMTrace.response, String).ilike(pattern),
                )
            )
        )

    # 1. KPI aggregate
    kpi_stmt = _apply_search(
        select(
            func.count().label("total_calls"),
            func.sum(case((LLMTrace.error.is_not(None), 1), else_=0)).label("error_calls"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
            func.avg(LLMTrace.elapsed_ms).label("avg_elapsed_ms"),
        ).where(*filters)
    )
    kpi_row = (await db.execute(kpi_stmt)).one()

    # 2. By model (skip NULL-model rows like MCP workflow-server invocations)
    by_model_stmt = _apply_search(
        select(
            LLMTrace.model.label("model"),
            LLMTrace.provider.label("provider"),
            func.count().label("calls"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
        )
        .where(*filters, LLMTrace.model.is_not(None))
        .group_by(LLMTrace.model, LLMTrace.provider)
        .order_by(func.coalesce(func.sum(LLMTrace.total_tokens), 0).desc())
    )
    by_model_rows = list((await db.execute(by_model_stmt)).all())

    # 3. By time + model
    bucket_expr = func.to_timestamp(
        func.floor(func.extract("epoch", LLMTrace.created_at) / bucket_seconds) * bucket_seconds
    ).label("bucket_ts")
    by_time_stmt = _apply_search(
        select(
            bucket_expr,
            LLMTrace.model.label("model"),
            func.count().label("calls"),
            func.sum(case((LLMTrace.error.is_(None), 1), else_=0)).label("success"),
            func.sum(case((LLMTrace.error.is_not(None), 1), else_=0)).label("error"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
        )
        .where(*filters)
        .group_by(bucket_expr, LLMTrace.model)
        .order_by(bucket_expr)
    )
    by_time_rows = list((await db.execute(by_time_stmt)).all())

    # Resolve costs once for all (model, prompt, completion) pairs from by_model
    model_pairs: list[tuple[str, int, int]] = [
        (r.model or "", int(r.prompt_tokens or 0), int(r.completion_tokens or 0))
        for r in by_model_rows
    ]
    model_costs = await resolve_costs_for_user(db, current_user.id, model_pairs)

    time_pairs: list[tuple[str, int, int]] = [
        (r.model or "", int(r.prompt_tokens or 0), int(r.completion_tokens or 0))
        for r in by_time_rows
    ]
    time_costs = await resolve_costs_for_user(db, current_user.id, time_pairs)

    # Build by_model with Top 8 + Other
    by_model: list[TraceStatsByModel] = []
    other_calls = 0
    other_tokens = 0
    other_cost = Decimal("0")
    for idx, (row, (cost, is_priced)) in enumerate(zip(by_model_rows, model_costs, strict=False)):
        cost_value = cost if cost is not None else Decimal("0")
        if idx < 8:
            by_model.append(
                TraceStatsByModel(
                    model=row.model or "(unknown)",
                    provider=row.provider,
                    calls=int(row.calls),
                    total_tokens=int(row.total_tokens or 0),
                    cost_usd=cost_value,
                    is_priced=is_priced,
                )
            )
        else:
            other_calls += int(row.calls)
            other_tokens += int(row.total_tokens or 0)
            other_cost += cost_value
    if other_calls > 0:
        by_model.append(
            TraceStatsByModel(
                model="Other",
                provider=None,
                calls=other_calls,
                total_tokens=other_tokens,
                cost_usd=other_cost,
                is_priced=True,
                is_other=True,
            )
        )

    # Fold by_time across models
    by_time_map: dict[datetime, dict] = {}
    for row, (cost, _is_priced) in zip(by_time_rows, time_costs, strict=False):
        bucket_ts = row.bucket_ts
        if bucket_ts.tzinfo is None:
            bucket_ts = bucket_ts.replace(tzinfo=timezone.utc)
        slot = by_time_map.setdefault(
            bucket_ts,
            {
                "calls": 0,
                "success": 0,
                "error": 0,
                "total_tokens": 0,
                "cost_usd": Decimal("0"),
            },
        )
        slot["calls"] += int(row.calls)
        slot["success"] += int(row.success or 0)
        slot["error"] += int(row.error or 0)
        slot["total_tokens"] += int(row.total_tokens or 0)
        if cost is not None:
            slot["cost_usd"] += cost

    by_time = [
        TraceStatsByTime(
            bucket_start=ts,
            calls=v["calls"],
            success=v["success"],
            error=v["error"],
            total_tokens=v["total_tokens"],
            cost_usd=v["cost_usd"],
        )
        for ts, v in sorted(by_time_map.items(), key=lambda kv: kv[0])
    ]

    total_calls = int(kpi_row.total_calls or 0)
    error_calls = int(kpi_row.error_calls or 0)
    success_calls = total_calls - error_calls
    error_pct = (error_calls / total_calls * 100.0) if total_calls else 0.0
    total_cost_usd = sum((m.cost_usd for m in by_model), Decimal("0"))
    unpriced_models = [m.model for m in by_model if not m.is_priced and not m.is_other]

    return TraceStatsResponse(
        range=TraceStatsRangeMeta(start=start_dt, end=end_dt, bucket_seconds=bucket_seconds),
        kpis=TraceStatsKpis(
            total_calls=total_calls,
            success_calls=success_calls,
            error_calls=error_calls,
            error_pct=round(error_pct, 2),
            prompt_tokens=int(kpi_row.prompt_tokens or 0),
            completion_tokens=int(kpi_row.completion_tokens or 0),
            total_tokens=int(kpi_row.total_tokens or 0),
            total_cost_usd=total_cost_usd,
            avg_latency_ms=float(kpi_row.avg_elapsed_ms or 0.0),
            unpriced_models=unpriced_models,
        ),
        by_model=by_model,
        by_time=by_time,
    )


@router.get("/{trace_id}", response_model=LLMTraceDetailResponse)
async def get_trace(
    trace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMTraceDetailResponse:
    """Fetch a single trace scoped to the current user."""
    result = await db.execute(
        select(LLMTrace, Credential.name, Workflow.name)
        .outerjoin(Credential, LLMTrace.credential_id == Credential.id)
        .outerjoin(Workflow, LLMTrace.workflow_id == Workflow.id)
        .where(LLMTrace.id == trace_id, LLMTrace.user_id == current_user.id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")
    trace, credential_name, workflow_name = row

    return LLMTraceDetailResponse(
        id=trace.id,
        created_at=trace.created_at,
        source=trace.source,
        request_type=trace.request_type,
        provider=trace.provider,
        model=trace.model,
        credential_id=trace.credential_id,
        credential_name=credential_name,
        workflow_id=trace.workflow_id,
        workflow_name=workflow_name,
        node_id=trace.node_id,
        node_label=trace.node_label,
        status="error" if trace.error else "success",
        elapsed_ms=trace.elapsed_ms,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        total_tokens=trace.total_tokens,
        request=trace.request,
        response=trace.response,
        error=trace.error,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_traces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all LLM traces for the current user."""
    await db.execute(delete(LLMTrace).where(LLMTrace.user_id == current_user.id))
    await db.commit()
