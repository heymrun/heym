"""Token and USD spend metric.

USD is resolved through ``resolve_costs_for_user`` - the same path the Traces tab
and the cost page use. A cost alert that disagrees with the cost page is worse
than no cost alert, so this must never grow its own pricing math.

Coding-agent (Codex / OpenCode) usage is intentionally excluded; this reads
``llm_traces`` only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models import LLMTrace
from app.services.alerts.context import AlertEvaluationContext, AlertObservation
from app.services.llm_pricing import resolve_costs_for_user


async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation:
    threshold = float(ctx.config.threshold)

    filters = [
        LLMTrace.user_id == ctx.owner_id,
        LLMTrace.created_at >= ctx.window_start,
        LLMTrace.created_at <= ctx.window_end,
    ]
    # An empty workflow_ids list means system scope with no workflow filter: LLM
    # calls made outside a workflow (Dashboard Chat, AI Assistant) carry
    # workflow_id NULL and are still this user's spend.
    if ctx.workflow_ids:
        filters.append(LLMTrace.workflow_id.in_(ctx.workflow_ids))

    result = await ctx.db.execute(
        select(
            LLMTrace.model,
            LLMTrace.prompt_tokens,
            LLMTrace.completion_tokens,
            LLMTrace.total_tokens,
            LLMTrace.workflow_id,
        ).where(*filters)
    )
    rows = list(result.all())

    by_model: dict[str, dict[str, float]] = {}
    # Spend spans workflows under system scope. Calls made outside any workflow
    # (Dashboard Chat, AI Assistant) carry no workflow_id and so are counted in the
    # total but cannot be attributed to a workflow.
    per_workflow: dict[uuid.UUID, float] = {}
    pairs: list[tuple[str, int, int]] = []
    workflow_ids: list[uuid.UUID | None] = []
    for model, prompt_tokens, completion_tokens, total_tokens, workflow_id in rows:
        key = str(model or "unknown")
        bucket = by_model.setdefault(key, {"total_tokens": 0, "usd": 0.0, "calls": 0})
        bucket["total_tokens"] += int(total_tokens or 0)
        bucket["calls"] += 1
        pairs.append((key, int(prompt_tokens or 0), int(completion_tokens or 0)))
        workflow_ids.append(workflow_id)
        if workflow_id is not None:
            per_workflow[workflow_id] = per_workflow.get(workflow_id, 0.0) + int(total_tokens or 0)

    if ctx.config.metric == "total_tokens":
        observed = float(sum(b["total_tokens"] for b in by_model.values()))
        return AlertObservation(
            observed_value=observed,
            threshold_value=threshold,
            context={
                "metric": "total_tokens",
                "by_model": by_model,
                "call_count": len(rows),
            },
            contributing_workflows=per_workflow,
        )

    # USD is a different unit from the tokens accumulated above, so the per-workflow
    # figures are rebuilt from the resolved costs rather than added to them.
    per_workflow = {}
    costs = await resolve_costs_for_user(ctx.db, ctx.owner_id, pairs)
    total_usd = 0.0
    unpriced: set[str] = set()
    for (model, _prompt, _completion), (cost, is_priced), workflow_id in zip(
        pairs, costs, workflow_ids, strict=False
    ):
        if not is_priced or cost is None:
            unpriced.add(model)
            continue
        total_usd += float(cost)
        by_model[model]["usd"] += float(cost)
        if workflow_id is not None:
            per_workflow[workflow_id] = per_workflow.get(workflow_id, 0.0) + float(cost)

    return AlertObservation(
        observed_value=round(total_usd, 6),
        threshold_value=threshold,
        context={
            "metric": "usd",
            "by_model": by_model,
            "call_count": len(rows),
            "unpriced_models": sorted(unpriced),
        },
        contributing_workflows=per_workflow,
    )
