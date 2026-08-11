"""Error-count-in-window metric.

Counts failed executions across the window rather than reacting to one failure,
because a single failed run is noise and a burst is an incident.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import ExecutionHistory
from app.services.alerts.context import AlertEvaluationContext, AlertObservation


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold_count)
    if not ctx.workflow_ids:
        return AlertObservation(observed_value=0.0, threshold_value=threshold, context={})

    window = (
        ExecutionHistory.workflow_id.in_(ctx.workflow_ids),
        ExecutionHistory.started_at >= ctx.window_start,
        ExecutionHistory.started_at <= ctx.window_end,
        ExecutionHistory.status == "error",
    )

    count_result = await ctx.db.execute(
        select(func.count()).select_from(ExecutionHistory).where(*window)
    )
    error_count = int(count_result.scalar() or 0)

    # Under system scope "12 errors" spans many workflows; the per-workflow split is
    # what turns the number into somewhere to look.
    per_workflow_result = await ctx.db.execute(
        select(ExecutionHistory.workflow_id, func.count())
        .where(*window)
        .group_by(ExecutionHistory.workflow_id)
    )

    return AlertObservation(
        observed_value=float(error_count),
        threshold_value=threshold,
        context={"error_count": error_count},
        contributing_workflows={
            workflow_id: float(count) for workflow_id, count in per_workflow_result.all()
        },
    )
