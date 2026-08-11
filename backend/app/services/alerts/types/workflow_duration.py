"""Workflow duration metric.

``p95`` delegates to the same ``calculate_percentile`` the Analytics tab uses, so
an alert and the latency chart never disagree about the same window.

Returning ``None`` below ``min_samples`` is deliberate: ``max`` over a single run
in a quiet window is just that run, which fires on noise rather than on a trend.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.api.analytics import calculate_percentile
from app.db.models import ExecutionHistory
from app.services.alerts.context import AlertEvaluationContext, AlertObservation


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold_ms)
    if not ctx.workflow_ids:
        return AlertObservation(observed_value=None, threshold_value=threshold, context={})

    result = await ctx.db.execute(
        select(ExecutionHistory.workflow_id, ExecutionHistory.execution_time_ms).where(
            ExecutionHistory.workflow_id.in_(ctx.workflow_ids),
            ExecutionHistory.started_at >= ctx.window_start,
            ExecutionHistory.started_at <= ctx.window_end,
        )
    )
    rows = [(row[0], float(row[1])) for row in result.all() if row[1] is not None]
    values = [value for _wid, value in rows]

    if len(values) < ctx.config.min_samples:
        return AlertObservation(
            observed_value=None,
            threshold_value=threshold,
            context={"sample_count": len(values), "min_samples": ctx.config.min_samples},
        )

    aggregation = ctx.config.aggregation
    if aggregation == "max":
        observed = max(values)
    elif aggregation == "avg":
        observed = sum(values) / len(values)
    else:
        observed = calculate_percentile(values, 95)

    # "max duration 6186ms" is unactionable under system scope without naming the
    # run behind it, so each workflow carries its own slowest run.
    per_workflow: dict[uuid.UUID, float] = {}
    for workflow_id, value in rows:
        per_workflow[workflow_id] = max(per_workflow.get(workflow_id, 0.0), value)

    return AlertObservation(
        observed_value=float(observed),
        threshold_value=threshold,
        context={
            "aggregation": aggregation,
            "sample_count": len(values),
            "max_ms": max(values),
            "avg_ms": sum(values) / len(values),
        },
        contributing_workflows=per_workflow,
    )
