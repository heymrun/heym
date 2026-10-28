"""Counts finished runs' nodes into node_analytics_snapshots, from the leader's scheduler loop.

A run is pending from its first write (``execution_history.node_analytics_pending`` defaults
to true) and is counted once, when a pass claims it after it has finished. Paused runs wait
for their resume. A writer that rewrites a finished row with more node results sets the
marker again in the same write: ``persist_run_history`` and the allowDownstream finalizers.
"""

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Select, Update, case, func, literal_column, select, true, update
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionHistory, NodeAnalyticsSnapshot
from app.db.session import async_session_maker
from app.services.analytics_metrics import normalize_bucket_start

ROLLUP_BATCH_SIZE = 200
MAX_BATCHES_PER_TICK = 5
_UNFINISHED_RUN_STATUSES = ("pending", "running")
_NOT_A_CALL = frozenset({"skipped", "pending"})
_ERROR_STATUSES = frozenset({"error", "timeout"})
_NODE_TYPE_MAX_LENGTH = 100


class NodeResultRow(Protocol):
    """One node result of a claimed run, projected to the fields the rollup reads."""

    workflow_id: uuid.UUID
    started_at: datetime | None
    node_type: str | None
    status: str | None
    execution_time_ms: str | None


@dataclass
class NodeAnalyticsDelta:
    """What one batch adds to one ``node_analytics_snapshots`` row."""

    workflow_id: uuid.UUID
    node_type: str
    bucket_start: datetime
    call_count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0


def _duration_ms(raw: str | None) -> float:
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    return value


def aggregate_node_rows(rows: Iterable[NodeResultRow]) -> list[NodeAnalyticsDelta]:
    """Sum calls, errors and duration per (workflow, node type, UTC hour), in a stable order.

    Skipped and pending results are not calls; error and timeout are calls and errors.
    """
    deltas: dict[tuple[uuid.UUID, str, datetime], NodeAnalyticsDelta] = {}
    for row in rows:
        node_type = (row.node_type or "").strip()[:_NODE_TYPE_MAX_LENGTH]
        status = (row.status or "").strip().lower()
        if not node_type or not status or status in _NOT_A_CALL or row.started_at is None:
            continue
        bucket_start = normalize_bucket_start(row.started_at)
        key = (row.workflow_id, node_type, bucket_start)
        delta = deltas.get(key)
        if delta is None:
            delta = NodeAnalyticsDelta(
                workflow_id=row.workflow_id, node_type=node_type, bucket_start=bucket_start
            )
            deltas[key] = delta
        delta.call_count += 1
        if status in _ERROR_STATUSES:
            delta.error_count += 1
        delta.total_duration_ms += _duration_ms(row.execution_time_ms)
    # A fixed order keeps the upsert's row locks in the same order across passes.
    return [deltas[key] for key in sorted(deltas, key=lambda k: (str(k[0]), k[2], k[1]))]


def pending_on_first_write(result: object) -> bool:
    """The marker for a run's first history write.

    False while allowDownstream work will rewrite the row with the rest of its node results;
    the finalizer sets it back to true together with the full list.
    """
    return not bool(getattr(result, "allow_downstream_pending", False))


def _claim_statement(batch_size: int) -> Select:
    return (
        select(ExecutionHistory.id)
        .where(
            ExecutionHistory.node_analytics_pending,
            ExecutionHistory.status.not_in(_UNFINISHED_RUN_STATUSES),
        )
        .order_by(ExecutionHistory.started_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )


def _node_rows_statement(run_ids: list[uuid.UUID]) -> Select:
    # Only three small fields per node leave the database; outputs stay where they are.
    node_results = case(
        (
            func.json_typeof(ExecutionHistory.node_results) == "array",
            ExecutionHistory.node_results,
        ),
        else_=literal_column("'[]'::json"),
    )
    node = func.json_array_elements(node_results).table_valued("value").lateral("node")
    return (
        select(
            ExecutionHistory.workflow_id,
            ExecutionHistory.started_at,
            node.c.value.op("->>")("node_type").label("node_type"),
            node.c.value.op("->>")("status").label("status"),
            node.c.value.op("->>")("execution_time_ms").label("execution_time_ms"),
        )
        .select_from(ExecutionHistory)
        .join(node, true())
        .where(ExecutionHistory.id.in_(run_ids))
    )


def _upsert_statement(deltas: list[NodeAnalyticsDelta]) -> Insert:
    stmt = pg_insert(NodeAnalyticsSnapshot).values(
        [
            {
                "id": uuid.uuid4(),
                "workflow_id": delta.workflow_id,
                "node_type": delta.node_type,
                "bucket_start": delta.bucket_start,
                "call_count": delta.call_count,
                "error_count": delta.error_count,
                "total_duration_ms": delta.total_duration_ms,
            }
            for delta in deltas
        ]
    )
    return stmt.on_conflict_do_update(
        constraint="uq_node_analytics_snapshot_scope",
        set_={
            "call_count": NodeAnalyticsSnapshot.call_count + stmt.excluded.call_count,
            "error_count": NodeAnalyticsSnapshot.error_count + stmt.excluded.error_count,
            "total_duration_ms": NodeAnalyticsSnapshot.total_duration_ms
            + stmt.excluded.total_duration_ms,
            "updated_at": func.now(),
        },
    )


def _clear_marker_statement(run_ids: list[uuid.UUID]) -> Update:
    return (
        update(ExecutionHistory)
        .where(ExecutionHistory.id.in_(run_ids))
        .values(node_analytics_pending=False)
    )


async def roll_up_node_analytics_batch(
    db: AsyncSession, *, batch_size: int = ROLLUP_BATCH_SIZE
) -> int:
    """Count one batch of finished pending runs and clear their marker; returns runs claimed.

    The claim's row locks and the marker update share one transaction, so two passes (a
    leader handoff) never count the same run twice.
    """
    run_ids = list((await db.execute(_claim_statement(batch_size))).scalars().all())
    if not run_ids:
        return 0
    deltas = aggregate_node_rows((await db.execute(_node_rows_statement(run_ids))).all())
    if deltas:
        await db.execute(_upsert_statement(deltas))
    await db.execute(_clear_marker_statement(run_ids))
    await db.commit()
    return len(run_ids)


async def roll_up_node_analytics() -> int:
    """One scheduler tick: up to MAX_BATCHES_PER_TICK batches; returns runs counted."""
    counted = 0
    for _ in range(MAX_BATCHES_PER_TICK):
        async with async_session_maker() as db:
            claimed = await roll_up_node_analytics_batch(db)
        counted += claimed
        if claimed < ROLLUP_BATCH_SIZE:
            break
    return counted
