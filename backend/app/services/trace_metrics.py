"""Which LLM traces a user sees, and the numbers behind the Traces tab.

A user sees their own traces only. The filter builders and the stats computation live here
so the Traces tab and Heym Work apply the same rules and show the same numbers. The module
imports no settings; price syncing stays with the router because Work never writes.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, LLMTrace, Workflow
from app.services.llm_pricing import resolve_costs_for_user

CostResolver = Callable[
    [AsyncSession, uuid.UUID, list[tuple[str, int, int]]],
    Awaitable[list[tuple[Decimal | None, bool]]],
]

RANGE_TABLE: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 300),
    "24h": (timedelta(hours=24), 3600),
    "7d": (timedelta(days=7), 6 * 3600),
    "30d": (timedelta(days=30), 86400),
}
TOP_MODELS = 8


@dataclass(frozen=True)
class TraceKpis:
    """Headline numbers; field names match ``TraceStatsKpis``."""

    total_calls: int
    success_calls: int
    error_calls: int
    error_pct: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_usd: Decimal
    avg_latency_ms: float
    unpriced_models: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TraceModelRow:
    """Calls and cost for one model; field names match ``TraceStatsByModel``."""

    model: str
    provider: str | None
    calls: int
    total_tokens: int
    cost_usd: Decimal
    is_priced: bool
    is_other: bool = False


@dataclass(frozen=True)
class TraceTimeRow:
    """One time bucket across models; field names match ``TraceStatsByTime``."""

    bucket_start: datetime
    calls: int
    success: int
    error: int
    total_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class TraceStats:
    """KPIs, top models and the time series for one window."""

    kpis: TraceKpis
    by_model: list[TraceModelRow]
    by_time: list[TraceTimeRow]


def resolve_range(
    range_key: str, *, now: datetime | None = None
) -> tuple[datetime | None, datetime, int]:
    """Returns (start_dt or None, end_dt, bucket_seconds). 'all' returns start=None.
    Unknown range_key falls back to '7d'."""
    now = now or datetime.now(timezone.utc)
    if range_key == "all":
        return (None, now, 86400)
    delta, bucket = RANGE_TABLE.get(range_key, RANGE_TABLE["7d"])
    return (now - delta, now, bucket)


def apply_source_filter(filters: list, source: str) -> None:
    """Apply source filter, including legacy expression-builder traces stored as assistant."""
    if source == "expression_builder":
        filters.append(
            or_(
                LLMTrace.source == "expression_builder",
                (LLMTrace.source == "assistant") & (LLMTrace.node_label == "Expression Builder"),
            )
        )
    elif source == "ai_ask":
        filters.append(
            (LLMTrace.source == "assistant") & (LLMTrace.node_label == "AI Ask"),
        )
    elif source == "ai_builder":
        filters.append(
            (LLMTrace.source == "assistant") & (LLMTrace.node_label == "AI Builder"),
        )
    else:
        filters.append(LLMTrace.source == source)


def trace_filters(
    user_id: uuid.UUID,
    *,
    credential_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    source: str | None = None,
    status: str | None = None,
) -> list:
    """WHERE clauses for the user's traces with the optional filters applied."""
    filters: list = [LLMTrace.user_id == user_id]
    if credential_id:
        filters.append(LLMTrace.credential_id == credential_id)
    if workflow_id:
        filters.append(LLMTrace.workflow_id == workflow_id)
    if source:
        apply_source_filter(filters, source)
    if status == "error":
        filters.append(LLMTrace.error.is_not(None))
    elif status == "success":
        filters.append(LLMTrace.error.is_(None))
    return filters


def trace_search_clause(search: str) -> ColumnElement[bool]:
    """Search across model, labels, workflow and credential names and the request and response.

    The statement must already join ``Workflow`` and ``Credential``.
    """
    pattern = f"%{search}%"
    return or_(
        LLMTrace.model.ilike(pattern),
        LLMTrace.router_label.ilike(pattern),
        LLMTrace.node_label.ilike(pattern),
        Workflow.name.ilike(pattern),
        Credential.name.ilike(pattern),
        cast(LLMTrace.request, String).ilike(pattern),
        cast(LLMTrace.response, String).ilike(pattern),
    )


def apply_trace_search(stmt: Select, search: str | None) -> Select:
    """Join the names the search reads and apply it; unchanged when there is no search."""
    if not search:
        return stmt
    return (
        stmt.outerjoin(Workflow, LLMTrace.workflow_id == Workflow.id)
        .outerjoin(Credential, LLMTrace.credential_id == Credential.id)
        .where(trace_search_clause(search))
    )


async def compute_trace_stats(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    filters: list,
    search: str | None,
    bucket_seconds: int,
    resolve_costs: CostResolver = resolve_costs_for_user,
) -> TraceStats:
    """KPIs, the top models (the rest folded into "Other") and the per-bucket series."""
    kpi_stmt = apply_trace_search(
        select(
            func.count().label("total_calls"),
            func.sum(case((LLMTrace.error.is_not(None), 1), else_=0)).label("error_calls"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
            func.avg(LLMTrace.elapsed_ms).label("avg_elapsed_ms"),
        ).where(*filters),
        search,
    )
    kpi_row = (await db.execute(kpi_stmt)).one()

    # Skip NULL-model rows like MCP workflow-server invocations.
    by_model_stmt = apply_trace_search(
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
        .order_by(func.coalesce(func.sum(LLMTrace.total_tokens), 0).desc()),
        search,
    )
    by_model_rows = list((await db.execute(by_model_stmt)).all())

    bucket_expr = func.to_timestamp(
        func.floor(func.extract("epoch", LLMTrace.created_at) / bucket_seconds) * bucket_seconds
    ).label("bucket_ts")
    by_time_stmt = apply_trace_search(
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
        .order_by(bucket_expr),
        search,
    )
    by_time_rows = list((await db.execute(by_time_stmt)).all())

    model_costs = await resolve_costs(
        db,
        user_id,
        [
            (r.model or "", int(r.prompt_tokens or 0), int(r.completion_tokens or 0))
            for r in by_model_rows
        ],
    )
    time_costs = await resolve_costs(
        db,
        user_id,
        [
            (r.model or "", int(r.prompt_tokens or 0), int(r.completion_tokens or 0))
            for r in by_time_rows
        ],
    )

    by_model: list[TraceModelRow] = []
    other_calls = 0
    other_tokens = 0
    other_cost = Decimal("0")
    for idx, (row, (cost, is_priced)) in enumerate(zip(by_model_rows, model_costs, strict=False)):
        cost_value = cost if cost is not None else Decimal("0")
        if idx < TOP_MODELS:
            by_model.append(
                TraceModelRow(
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
            TraceModelRow(
                model="Other",
                provider=None,
                calls=other_calls,
                total_tokens=other_tokens,
                cost_usd=other_cost,
                is_priced=True,
                is_other=True,
            )
        )

    by_time_map: dict[datetime, dict] = {}
    for row, (cost, _is_priced) in zip(by_time_rows, time_costs, strict=False):
        bucket_ts = row.bucket_ts
        if bucket_ts.tzinfo is None:
            bucket_ts = bucket_ts.replace(tzinfo=timezone.utc)
        slot = by_time_map.setdefault(
            bucket_ts,
            {"calls": 0, "success": 0, "error": 0, "total_tokens": 0, "cost_usd": Decimal("0")},
        )
        slot["calls"] += int(row.calls)
        slot["success"] += int(row.success or 0)
        slot["error"] += int(row.error or 0)
        slot["total_tokens"] += int(row.total_tokens or 0)
        if cost is not None:
            slot["cost_usd"] += cost

    total_calls = int(kpi_row.total_calls or 0)
    error_calls = int(kpi_row.error_calls or 0)
    return TraceStats(
        kpis=TraceKpis(
            total_calls=total_calls,
            success_calls=total_calls - error_calls,
            error_calls=error_calls,
            error_pct=round((error_calls / total_calls * 100.0) if total_calls else 0.0, 2),
            prompt_tokens=int(kpi_row.prompt_tokens or 0),
            completion_tokens=int(kpi_row.completion_tokens or 0),
            total_tokens=int(kpi_row.total_tokens or 0),
            total_cost_usd=sum((m.cost_usd for m in by_model), Decimal("0")),
            avg_latency_ms=float(kpi_row.avg_elapsed_ms or 0.0),
            unpriced_models=[m.model for m in by_model if not m.is_priced and not m.is_other],
        ),
        by_model=by_model,
        by_time=[
            TraceTimeRow(bucket_start=ts, **values)
            for ts, values in sorted(by_time_map.items(), key=lambda kv: kv[0])
        ],
    )
