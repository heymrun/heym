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

from app.services.analytics_metrics import normalize_bucket_start

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
