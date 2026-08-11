"""Execution-count-in-window metric.

Answers "did this run far more often than it should have". The trigger-source
breakdown is in the context because a runaway run count is almost always
explained by which trigger fired it.
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
    )

    count_result = await ctx.db.execute(
        select(func.count()).select_from(ExecutionHistory).where(*window)
    )
    total = int(count_result.scalar() or 0)

    breakdown_result = await ctx.db.execute(
        select(ExecutionHistory.trigger_source, func.count())
        .where(*window)
        .group_by(ExecutionHistory.trigger_source)
    )
    by_source = {str(source or "unknown"): int(count) for source, count in breakdown_result.all()}

    # Under system scope the total spans many workflows, so the count alone does not
    # say which one started running away.
    per_workflow_result = await ctx.db.execute(
        select(ExecutionHistory.workflow_id, func.count())
        .where(*window)
        .group_by(ExecutionHistory.workflow_id)
    )

    return AlertObservation(
        observed_value=float(total),
        threshold_value=threshold,
        context={"execution_count": total, "by_trigger_source": by_source},
        contributing_workflows={
            workflow_id: float(count) for workflow_id, count in per_workflow_result.all()
        },
    )
