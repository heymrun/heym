"""Node type rankings and series for the Analytics tab, read from node_analytics_snapshots.

Reads select explicit columns and the module imports no settings, like analytics_metrics.
It never touches execution_history: the rollup already counted what it needs.
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NodeAnalyticsSnapshot
from app.services.analytics_metrics import bucket_by_size, bucket_keys


@dataclass(frozen=True)
class NodeTypeSeries:
    """One node type's window total and per-bucket values; matches ``NodeTypeSeriesItem``."""

    node_type: str
    total: float
    average: float | None
    values: list[float | None]


@dataclass(frozen=True)
class NodeTypeAnalytics:
    """Three top-N rankings over one window; matches ``NodeTypeAnalyticsResponse``."""

    time_buckets: list[str] = field(default_factory=list)
    most_duration: list[NodeTypeSeries] = field(default_factory=list)
    most_errors: list[NodeTypeSeries] = field(default_factory=list)
    most_calls: list[NodeTypeSeries] = field(default_factory=list)


@dataclass(frozen=True)
class NodeTypeTotals:
    """One node type's totals over a whole window."""

    node_type: str
    call_count: int
    error_count: int
    total_duration_ms: float


class NodeTypeBucketRow(Protocol):
    """One (node type, hour) sum from ``node_analytics_snapshots``."""

    node_type: str
    bucket_start: datetime
    call_count: int | None
    error_count: int | None
    total_duration_ms: float | None


@dataclass
class _Counts:
    calls: int = 0
    errors: int = 0
    duration_ms: float = 0.0


def _average(counts: _Counts) -> float | None:
    return counts.duration_ms / counts.calls if counts.calls > 0 else None


def rank_node_types(
    rows: Iterable[NodeTypeBucketRow],
    *,
    time_buckets: list[str],
    bucket_delta: timedelta,
    limit: int,
) -> NodeTypeAnalytics:
    """Fold hourly rows into ``time_buckets`` and keep the top ``limit`` types per metric.

    Duration is ranked by total time and plotted as average time per call (None for a
    bucket without calls). Errors list only types that failed. Ties break on the type name.
    """
    position_by_bucket = {key: index for index, key in enumerate(time_buckets)}
    totals: dict[str, _Counts] = {}
    per_bucket: dict[str, list[_Counts]] = {}
    for row in rows:
        bucket = bucket_by_size(row.bucket_start, bucket_delta).isoformat()
        position = position_by_bucket.get(bucket)
        if position is None:
            continue
        series = per_bucket.setdefault(row.node_type, [_Counts() for _ in time_buckets])
        total = totals.setdefault(row.node_type, _Counts())
        for counts in (series[position], total):
            counts.calls += int(row.call_count or 0)
            counts.errors += int(row.error_count or 0)
            counts.duration_ms += float(row.total_duration_ms or 0.0)

    def top(metric: Callable[[_Counts], float]) -> list[str]:
        ranked = sorted(
            (node_type for node_type, counts in totals.items() if metric(counts) > 0),
            key=lambda node_type: (-metric(totals[node_type]), node_type),
        )
        return ranked[:limit]

    return NodeTypeAnalytics(
        time_buckets=time_buckets,
        most_duration=[
            NodeTypeSeries(
                node_type=node_type,
                total=totals[node_type].duration_ms,
                average=_average(totals[node_type]),
                values=[_average(counts) for counts in per_bucket[node_type]],
            )
            for node_type in top(lambda counts: counts.duration_ms)
        ],
        most_errors=[
            NodeTypeSeries(
                node_type=node_type,
                total=float(totals[node_type].errors),
                average=None,
                values=[float(counts.errors) for counts in per_bucket[node_type]],
            )
            for node_type in top(lambda counts: counts.errors)
        ],
        most_calls=[
            NodeTypeSeries(
                node_type=node_type,
                total=float(totals[node_type].calls),
                average=None,
                values=[float(counts.calls) for counts in per_bucket[node_type]],
            )
            for node_type in top(lambda counts: counts.calls)
        ],
    )


def _scope(
    accessible_workflow_ids: list[uuid.UUID], workflow_id: uuid.UUID | None
) -> ColumnElement[bool] | None:
    """The rows a user may read: one workflow or every accessible one; None reads nothing."""
    if not accessible_workflow_ids:
        return None
    if workflow_id is not None:
        if workflow_id not in accessible_workflow_ids:
            return None
        return NodeAnalyticsSnapshot.workflow_id == workflow_id
    return NodeAnalyticsSnapshot.workflow_id.in_(accessible_workflow_ids)


async def compute_node_type_totals(
    db: AsyncSession,
    *,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    since: datetime,
    until: datetime,
) -> list[NodeTypeTotals]:
    """Calls, errors and total duration per node type over ``[since, until)``."""
    scope = _scope(accessible_workflow_ids, workflow_id)
    if scope is None:
        return []
    rows = (
        await db.execute(
            select(
                NodeAnalyticsSnapshot.node_type,
                func.sum(NodeAnalyticsSnapshot.call_count).label("call_count"),
                func.sum(NodeAnalyticsSnapshot.error_count).label("error_count"),
                func.sum(NodeAnalyticsSnapshot.total_duration_ms).label("total_duration_ms"),
            )
            .where(
                scope,
                NodeAnalyticsSnapshot.bucket_start >= since,
                NodeAnalyticsSnapshot.bucket_start < until,
            )
            .group_by(NodeAnalyticsSnapshot.node_type)
        )
    ).all()
    return [
        NodeTypeTotals(
            node_type=row.node_type,
            call_count=int(row.call_count or 0),
            error_count=int(row.error_count or 0),
            total_duration_ms=float(row.total_duration_ms or 0.0),
        )
        for row in rows
    ]


async def compute_node_type_analytics(
    db: AsyncSession,
    *,
    accessible_workflow_ids: list[uuid.UUID],
    workflow_id: uuid.UUID | None,
    since: datetime,
    until: datetime,
    bucket_delta: timedelta,
    limit: int = 10,
) -> NodeTypeAnalytics:
    """Top node types by total duration, errors and calls over ``[since, until)``."""
    time_buckets = bucket_keys(since, until, bucket_delta)
    scope = _scope(accessible_workflow_ids, workflow_id)
    if scope is None:
        return NodeTypeAnalytics(time_buckets=time_buckets)
    rows = (
        await db.execute(
            select(
                NodeAnalyticsSnapshot.node_type,
                NodeAnalyticsSnapshot.bucket_start,
                func.sum(NodeAnalyticsSnapshot.call_count).label("call_count"),
                func.sum(NodeAnalyticsSnapshot.error_count).label("error_count"),
                func.sum(NodeAnalyticsSnapshot.total_duration_ms).label("total_duration_ms"),
            )
            .where(
                scope,
                NodeAnalyticsSnapshot.bucket_start >= since,
                NodeAnalyticsSnapshot.bucket_start < until,
            )
            .group_by(NodeAnalyticsSnapshot.node_type, NodeAnalyticsSnapshot.bucket_start)
        )
    ).all()
    return rank_node_types(rows, time_buckets=time_buckets, bucket_delta=bucket_delta, limit=limit)
