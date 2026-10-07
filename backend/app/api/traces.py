import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
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
from app.services import trace_metrics
from app.services.llm_pricing import resolve_costs_for_user
from app.services.llm_pricing_sync import ensure_pricing_synced
from app.services.trace_metrics import apply_source_filter as _apply_source_filter
from app.services.trace_metrics import resolve_range as _resolve_range

__all__ = ["_apply_source_filter", "_resolve_range", "router"]

router = APIRouter()


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
    filters = trace_metrics.trace_filters(
        current_user.id,
        credential_id=credential_id,
        workflow_id=workflow_id,
        source=source,
        status=status_filter,
    )
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
        base_query = base_query.where(trace_metrics.trace_search_clause(search))

    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    order_by = LLMTrace.created_at.asc() if order == "asc" else LLMTrace.created_at.desc()
    result = await db.execute(base_query.order_by(order_by).limit(limit).offset(offset))
    rows = result.all()
    cost_pairs = [
        (trace.model or "", int(trace.prompt_tokens or 0), int(trace.completion_tokens or 0))
        for trace, _, _ in rows
    ]
    resolved_costs = (
        await resolve_costs_for_user(db, current_user.id, cost_pairs) if cost_pairs else []
    )

    items: list[LLMTraceListItem] = []
    for index, (trace, credential_name, workflow_name) in enumerate(rows):
        cost_usd, is_priced = (
            resolved_costs[index] if index < len(resolved_costs) else (None, False)
        )
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
                router_credential_id=trace.router_credential_id,
                router_label=trace.router_label,
                workflow_id=trace.workflow_id,
                workflow_name=workflow_name,
                node_id=trace.node_id,
                node_label=trace.node_label,
                status="error" if trace.error else "success",
                elapsed_ms=trace.elapsed_ms,
                prompt_tokens=trace.prompt_tokens,
                completion_tokens=trace.completion_tokens,
                total_tokens=trace.total_tokens,
                cost_usd=cost_usd,
                is_priced=is_priced,
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
    filters = trace_metrics.trace_filters(
        current_user.id,
        credential_id=credential_id,
        workflow_id=workflow_id,
        source=source,
        status=status_filter,
    )
    if start_dt is not None:
        filters.append(LLMTrace.created_at >= start_dt)

    stats = await trace_metrics.compute_trace_stats(
        db,
        user_id=current_user.id,
        filters=filters,
        search=search,
        bucket_seconds=bucket_seconds,
        resolve_costs=resolve_costs_for_user,
    )
    return TraceStatsResponse(
        range=TraceStatsRangeMeta(start=start_dt, end=end_dt, bucket_seconds=bucket_seconds),
        kpis=TraceStatsKpis(**asdict(stats.kpis)),
        by_model=[TraceStatsByModel(**asdict(row)) for row in stats.by_model],
        by_time=[TraceStatsByTime(**asdict(row)) for row in stats.by_time],
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
    [(cost_usd, is_priced)] = await resolve_costs_for_user(
        db,
        current_user.id,
        [(trace.model or "", int(trace.prompt_tokens or 0), int(trace.completion_tokens or 0))],
    )

    return LLMTraceDetailResponse(
        id=trace.id,
        created_at=trace.created_at,
        source=trace.source,
        request_type=trace.request_type,
        provider=trace.provider,
        model=trace.model,
        credential_id=trace.credential_id,
        credential_name=credential_name,
        router_credential_id=trace.router_credential_id,
        router_label=trace.router_label,
        workflow_id=trace.workflow_id,
        workflow_name=workflow_name,
        node_id=trace.node_id,
        node_label=trace.node_label,
        status="error" if trace.error else "success",
        elapsed_ms=trace.elapsed_ms,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        total_tokens=trace.total_tokens,
        cost_usd=cost_usd,
        is_priced=is_priced,
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
