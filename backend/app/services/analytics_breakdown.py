"""Where runs fail and why they are slow, by workflow and by node type, for the chat engine.

Chat's ``get_analytics_breakdown`` tool reads this, and with it ``heym_chat`` over MCP and
the Heym Agent over A2A. It ranks the same rollups as the Analytics tab: the workflow
totals behind its tables and the node type totals behind its Node Types charts. Totals
only, no per-bucket series, so the model reads a short answer.
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TypeVar

from app.services.analytics_metrics import WorkflowBreakdownRow
from app.services.node_analytics_metrics import NodeTypeTotals

NODE_DATA_NOTE = (
    "No node analytics in this window yet: node types are counted for runs that finished "
    "after node analytics were added."
)

_Item = TypeVar("_Item")


@dataclass(frozen=True)
class WorkflowSummary:
    """One workflow's runs, errors and average latency over the window."""

    workflow_id: uuid.UUID
    workflow_name: str
    execution_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float


@dataclass(frozen=True)
class NodeTypeSummary:
    """One node type's calls, errors and time over the window."""

    node_type: str
    call_count: int
    error_count: int
    error_rate: float
    total_duration_ms: float
    avg_duration_ms: float | None


@dataclass(frozen=True)
class AnalyticsBreakdown:
    """The rankings the chat tool returns, each at most ``limit`` long."""

    time_range: str
    workflows_run: int = 0
    executions: int = 0
    most_run_workflows: list[WorkflowSummary] = field(default_factory=list)
    most_failed_workflows: list[WorkflowSummary] = field(default_factory=list)
    slowest_workflows: list[WorkflowSummary] = field(default_factory=list)
    node_types_by_time: list[NodeTypeSummary] = field(default_factory=list)
    node_types_by_errors: list[NodeTypeSummary] = field(default_factory=list)
    node_types_by_calls: list[NodeTypeSummary] = field(default_factory=list)
    note: str | None = None


def _top(
    items: Iterable[_Item],
    metric: Callable[[_Item], float],
    name: Callable[[_Item], str],
    limit: int,
) -> list[_Item]:
    ranked = sorted(
        (item for item in items if metric(item) > 0), key=lambda i: (-metric(i), name(i))
    )
    return ranked[:limit]


def _workflow_summary(row: WorkflowBreakdownRow) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=row.workflow_id,
        workflow_name=row.workflow_name,
        execution_count=row.execution_count,
        error_count=row.error_count,
        error_rate=round(row.error_rate, 1),
        avg_latency_ms=round(row.avg_latency_ms, 1),
    )


def _node_type_summary(totals: NodeTypeTotals) -> NodeTypeSummary:
    calls = totals.call_count
    return NodeTypeSummary(
        node_type=totals.node_type,
        call_count=calls,
        error_count=totals.error_count,
        error_rate=round(totals.error_count / calls * 100, 1) if calls else 0.0,
        total_duration_ms=round(totals.total_duration_ms, 1),
        avg_duration_ms=round(totals.total_duration_ms / calls, 1) if calls else None,
    )


def build_analytics_breakdown(
    time_range: str,
    workflows: Iterable[WorkflowBreakdownRow],
    node_types: Iterable[NodeTypeTotals],
    *,
    limit: int,
) -> AnalyticsBreakdown:
    """Rank workflows by runs, errors and latency, and node types by time, errors and calls."""
    workflow_rows = [_workflow_summary(row) for row in workflows if row.execution_count > 0]
    node_rows = [_node_type_summary(totals) for totals in node_types if totals.call_count > 0]

    def workflow_name(item: WorkflowSummary) -> str:
        return item.workflow_name

    def node_type(item: NodeTypeSummary) -> str:
        return item.node_type

    return AnalyticsBreakdown(
        time_range=time_range,
        workflows_run=len(workflow_rows),
        executions=sum(row.execution_count for row in workflow_rows),
        most_run_workflows=_top(workflow_rows, lambda w: w.execution_count, workflow_name, limit),
        most_failed_workflows=_top(workflow_rows, lambda w: w.error_count, workflow_name, limit),
        slowest_workflows=_top(workflow_rows, lambda w: w.avg_latency_ms, workflow_name, limit),
        node_types_by_time=_top(node_rows, lambda n: n.total_duration_ms, node_type, limit),
        node_types_by_errors=_top(node_rows, lambda n: n.error_count, node_type, limit),
        node_types_by_calls=_top(node_rows, lambda n: n.call_count, node_type, limit),
        note=None if node_rows else NODE_DATA_NOTE,
    )
