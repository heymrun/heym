"""Agent Suite numbers: one agent node's latest runs, read from its LLM traces.

An agent node writes one trace per run, carrying its tokens, its model time and the
tool calls it made, so latency, cost, tokens and tool usage all come from that one row.
Cost goes through ``llm_pricing`` and percentiles through ``calculate_percentile`` so the
suite agrees with the Traces and Analytics tabs about the same runs.
"""

import math
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import JSON, ColumnElement, case, cast, func, literal, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMTrace, Workflow
from app.services.agent_tool_observability import resolve_tool_call_status, summarize_tool_calls
from app.services.agent_tool_policy import NodeTool
from app.services.analytics_metrics import calculate_percentile
from app.services.llm_pricing import resolve_costs_for_user
from app.services.workflow_access import workflow_access_clause

CostResolver = Callable[
    [AsyncSession, uuid.UUID, list[tuple[str, int, int]]],
    Awaitable[list[tuple[Decimal | None, bool]]],
]

AGENT_NODE_TYPE = "agent"
# Rows an agent node writes besides its own run: compression, guardrails, routing.
AUXILIARY_REQUEST_TYPES = ("context.compression", "guardrail_classification", "decision.systemone")
DEFAULT_RUN_LIMIT = 10
MAX_RUN_LIMIT = 50
THRESHOLD_HEADROOM = 1.2
FAILED_TOOL_STATUSES = frozenset({"error", "timeout", "cancelled"})

ToolExpect = Literal["called", "not_called"]
ToolKind = Literal["tool", "mcp", "sub_agent", "sub_workflow", "skill", "node", "review"]
# The trace records where each tool came from; Python tools carry no source.
KIND_BY_SOURCE: dict[str, ToolKind] = {
    "mcp": "mcp",
    "sub_agent": "sub_agent",
    "sub_workflow": "sub_workflow",
    "skill": "skill",
    "node_tool": "node",
    "hitl": "review",
}
KIND_LABELS: dict[str, str] = {
    "tool": "",
    "mcp": "MCP tool ",
    "sub_agent": "sub-agent ",
    "sub_workflow": "sub-workflow ",
    "skill": "skill ",
    "node": "node tool ",
    "review": "review step ",
}
CheckStatus = Literal["pass", "fail", "skip"]
CheckKind = Literal["run", "assertion", "threshold"]


@dataclass(frozen=True)
class AgentToolCall:
    """One tool call inside a run, without its arguments or result.

    ``kind`` and ``name`` identify what was called: a sub-agent by its label, a
    sub-workflow by its id and a skill by its name, rather than the generic tool name.
    """

    kind: str
    name: str
    label: str
    status: str
    elapsed_ms: float | None
    server: str | None = None


@dataclass(frozen=True)
class AgentRun:
    """One run of the agent, as its trace recorded it."""

    trace_id: uuid.UUID
    created_at: datetime
    model: str | None
    latency_ms: float
    model_ms: float
    tool_ms: float
    cost_usd: float | None
    total_tokens: int
    tool_count: int
    tool_calls: list[AgentToolCall]
    error: str | None


@dataclass(frozen=True)
class AgentBaseline:
    """Aggregates over the runs that finished without an error."""

    run_count: int = 0
    error_count: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    cost_avg_usd: float | None = None
    cost_p95_usd: float | None = None
    tokens_avg: float | None = None
    tokens_p95: float | None = None
    tool_calls_avg: float | None = None
    tool_calls_max: int | None = None
    unpriced_models: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfiguredTool:
    kind: str
    name: str
    label: str


@dataclass(frozen=True)
class AgentToolUsage:
    """How often the agent used one tool across the runs."""

    kind: str
    name: str
    label: str
    server: str | None
    configured: bool
    runs_called: int
    call_count: int
    error_count: int
    avg_ms: float | None


@dataclass(frozen=True)
class AgentCandidate:
    """An agent node the user can pick, with how many of its runs their traces hold."""

    workflow_id: uuid.UUID
    workflow_name: str
    node_id: str
    node_label: str
    run_count: int
    last_run_at: datetime | None


@dataclass(frozen=True)
class ToolExpectation:
    name: str
    expect: ToolExpect
    kind: str = "tool"
    label: str | None = None


@dataclass(frozen=True)
class AgentThresholds:
    """Upper bounds per run; None turns that check off."""

    latency_ms: float | None = None
    cost_usd: float | None = None
    total_tokens: int | None = None
    tool_calls: int | None = None


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    kind: CheckKind
    status: CheckStatus
    detail: str | None = None


@dataclass(frozen=True)
class RunEvaluation:
    run: AgentRun
    passed: bool
    checks: list[CheckResult]


@dataclass(frozen=True)
class CheckSummary:
    key: str
    label: str
    kind: CheckKind
    passed: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    baseline: float | None
    current: float | None
    delta_pct: float | None


@dataclass(frozen=True)
class AgentReport:
    run_count: int
    passed_count: int
    pass_rate: float | None
    checks: list[CheckSummary]
    current: AgentBaseline
    deltas: list[MetricDelta]
    runs: list[RunEvaluation]


def find_agent_node(nodes: Any, node_id: str) -> dict[str, Any] | None:
    """Return the agent node with ``node_id`` from a workflow's node list."""
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if (
            isinstance(node, dict)
            and node.get("id") == node_id
            and node.get("type") == AGENT_NODE_TYPE
        ):
            return node
    return None


def agent_node_label(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    label = data.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else str(node.get("id"))


def skill_tool_name(skill_name: str) -> str:
    """The name a skill's tool gets, without its ``skill_`` prefix."""
    return skill_name.replace(" ", "_").lower()


def configured_tools(
    node: dict[str, Any],
    workflow_names: dict[str, str] | None = None,
    *,
    node_tools: Sequence[NodeTool] = (),
) -> list[ConfiguredTool]:
    """Tools known from the node's settings and the nodes on its tool input. MCP tools
    only show up once called."""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    found: list[ConfiguredTool] = []
    for tool in data.get("tools") or []:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"].strip():
            found.append(ConfiguredTool("tool", tool["name"].strip(), tool["name"].strip()))
    for skill in data.get("skills") or []:
        if isinstance(skill, dict) and isinstance(skill.get("name"), str) and skill["name"].strip():
            label = skill["name"].strip()
            found.append(ConfiguredTool("skill", skill_tool_name(label), label))
    if data.get("isOrchestrator"):
        for label in data.get("subAgentLabels") or []:
            if isinstance(label, str) and label.strip():
                found.append(ConfiguredTool("sub_agent", label.strip(), label.strip()))
    configured_names = data.get("subWorkflowNames")
    configured_names = configured_names if isinstance(configured_names, dict) else {}
    for workflow_id in data.get("subWorkflowIds") or []:
        if not isinstance(workflow_id, str) or not workflow_id:
            continue
        label = configured_names.get(workflow_id) or (workflow_names or {}).get(workflow_id)
        found.append(ConfiguredTool("sub_workflow", workflow_id, label or workflow_id))
    for tool in node_tools:
        found.append(ConfiguredTool("node", tool.name, tool.label))
    unique: dict[tuple[str, str], ConfiguredTool] = {}
    for tool in found:
        unique.setdefault((tool.kind, tool.name), tool)
    return list(unique.values())


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def tool_call_from_entry(entry: dict[str, Any]) -> AgentToolCall:
    """Identify one recorded tool call by what it reached, not by the generic tool name."""
    raw_name = _text(entry.get("name")) or "tool"
    kind = KIND_BY_SOURCE.get(str(entry.get("source") or ""), "tool")
    arguments = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
    name = label = raw_name
    if kind == "sub_agent":
        name = label = _text(arguments.get("sub_agent_label")) or raw_name
    elif kind == "sub_workflow":
        name = _text(arguments.get("workflow_id")) or raw_name
        label = _text(entry.get("workflow_name")) or name
    elif kind == "skill":
        name = label = raw_name.removeprefix("skill_")
    elapsed = entry.get("elapsed_ms")
    return AgentToolCall(
        kind=kind,
        name=name,
        label=label,
        status=resolve_tool_call_status(entry),
        elapsed_ms=round(float(elapsed), 2) if isinstance(elapsed, (int, float)) else None,
        server=_text(entry.get("mcp_server")),
    )


def _as_float(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _run_from_row(row: Any, cost_usd: Decimal | None) -> AgentRun:
    tool_calls_raw = row.tool_calls if isinstance(row.tool_calls, list) else []
    metrics = row.tool_metrics
    # The trace keeps at most 100 call records; its tool_metrics counted every call.
    if not isinstance(metrics, dict):
        metrics = summarize_tool_calls(tool_calls_raw)
    tool_calls = [
        tool_call_from_entry(entry)
        for entry in tool_calls_raw
        if isinstance(entry, dict) and entry.get("name") != "_context_compression"
    ]
    model_ms = _as_float(row.elapsed_ms)
    tool_ms = _as_float(metrics.get("total_duration_ms"))
    return AgentRun(
        trace_id=row.id,
        created_at=row.created_at,
        model=row.model,
        latency_ms=round(model_ms + tool_ms, 2),
        model_ms=round(model_ms, 2),
        tool_ms=round(tool_ms, 2),
        cost_usd=float(cost_usd) if cost_usd is not None else None,
        total_tokens=int(row.total_tokens or 0),
        tool_count=int(metrics.get("count") or 0),
        tool_calls=tool_calls,
        error=row.error,
    )


def _agent_trace_filters(user_id: uuid.UUID) -> list[ColumnElement[bool]]:
    return [
        LLMTrace.user_id == user_id,
        LLMTrace.source == "workflow",
        LLMTrace.request_type.not_in(AUXILIARY_REQUEST_TYPES),
    ]


async def list_agent_nodes(db: AsyncSession, *, user_id: uuid.UUID) -> list[AgentCandidate]:
    """Every agent node in the workflows the user can reach, those run most recently first."""
    nodes_array = case(
        (func.json_typeof(Workflow.nodes) == "array", Workflow.nodes),
        else_=cast(literal("[]"), JSON),
    )
    element = func.json_array_elements(nodes_array).table_valued("value").lateral()
    node = element.c.value
    node_id = node.op("->>")("id")
    rows = (
        await db.execute(
            select(
                Workflow.id,
                Workflow.name,
                node_id.label("node_id"),
                node.op("->")("data").op("->>")("label").label("node_label"),
            )
            .select_from(Workflow)
            .join(element, true())
            .where(
                workflow_access_clause(user_id),
                Workflow.kind == "workflow",
                node.op("->>")("type") == AGENT_NODE_TYPE,
                node_id.is_not(None),
            )
        )
    ).all()
    if not rows:
        return []
    counts = (
        await db.execute(
            select(
                LLMTrace.workflow_id,
                LLMTrace.node_id,
                func.count().label("run_count"),
                func.max(LLMTrace.created_at).label("last_run_at"),
            )
            .where(
                *_agent_trace_filters(user_id),
                LLMTrace.workflow_id.in_({row.id for row in rows}),
            )
            .group_by(LLMTrace.workflow_id, LLMTrace.node_id)
        )
    ).all()
    by_node = {(row.workflow_id, row.node_id): row for row in counts}
    candidates = []
    for row in rows:
        usage = by_node.get((row.id, row.node_id))
        label = row.node_label.strip() if isinstance(row.node_label, str) else ""
        candidates.append(
            AgentCandidate(
                workflow_id=row.id,
                workflow_name=row.name,
                node_id=row.node_id,
                node_label=label or row.node_id,
                run_count=usage.run_count if usage else 0,
                last_run_at=usage.last_run_at if usage else None,
            )
        )
    candidates.sort(key=lambda c: (c.workflow_name.lower(), c.node_label.lower()))
    candidates.sort(key=lambda c: c.last_run_at.timestamp() if c.last_run_at else 0, reverse=True)
    return candidates


async def load_agent_runs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    workflow_id: uuid.UUID,
    node_id: str,
    limit: int = DEFAULT_RUN_LIMIT,
    trace_ids: list[uuid.UUID] | None = None,
    cost_resolver: CostResolver = resolve_costs_for_user,
) -> list[AgentRun]:
    """The agent's latest runs, newest first, or exactly ``trace_ids`` when given.

    A user sees their own traces only.
    """
    stmt = (
        select(
            LLMTrace.id,
            LLMTrace.created_at,
            LLMTrace.model,
            LLMTrace.prompt_tokens,
            LLMTrace.completion_tokens,
            LLMTrace.total_tokens,
            LLMTrace.elapsed_ms,
            LLMTrace.error,
            LLMTrace.response["tool_calls"].label("tool_calls"),
            LLMTrace.response["tool_metrics"].label("tool_metrics"),
        )
        .where(
            *_agent_trace_filters(user_id),
            LLMTrace.workflow_id == workflow_id,
            LLMTrace.node_id == node_id,
        )
        .order_by(LLMTrace.created_at.desc(), LLMTrace.id.desc())
    )
    if trace_ids is not None:
        if not trace_ids:
            return []
        stmt = stmt.where(LLMTrace.id.in_(trace_ids))
    else:
        stmt = stmt.limit(max(1, min(limit, MAX_RUN_LIMIT)))
    rows = (await db.execute(stmt)).all()
    priced_rows = [row for row in rows if row.model]
    costs = await cost_resolver(
        db,
        user_id,
        [
            (row.model, int(row.prompt_tokens or 0), int(row.completion_tokens or 0))
            for row in priced_rows
        ],
    )
    cost_by_id = {row.id: cost for row, (cost, _priced) in zip(priced_rows, costs)}
    return [_run_from_row(row, cost_by_id.get(row.id)) for row in rows]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rounded(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def summarize_runs(runs: list[AgentRun]) -> AgentBaseline:
    """Latency, cost, token and tool-call aggregates over the runs without an error."""
    ok = [run for run in runs if run.error is None]
    error_count = len(runs) - len(ok)
    if not ok:
        return AgentBaseline(error_count=error_count)
    latencies = [run.latency_ms for run in ok]
    costs = [run.cost_usd for run in ok if run.cost_usd is not None]
    tokens = [float(run.total_tokens) for run in ok]
    tool_counts = [float(run.tool_count) for run in ok]
    return AgentBaseline(
        run_count=len(ok),
        error_count=error_count,
        latency_p50_ms=round(calculate_percentile(latencies, 50), 1),
        latency_p95_ms=round(calculate_percentile(latencies, 95), 1),
        cost_avg_usd=_rounded(_mean(costs), 6),
        cost_p95_usd=round(calculate_percentile(costs, 95), 6) if costs else None,
        tokens_avg=_rounded(_mean(tokens), 1),
        tokens_p95=calculate_percentile(tokens, 95),
        tool_calls_avg=_rounded(_mean(tool_counts), 2),
        tool_calls_max=int(max(tool_counts)),
        unpriced_models=sorted({run.model for run in ok if run.cost_usd is None and run.model}),
    )


def summarize_tool_usage(
    runs: list[AgentRun], configured: list[ConfiguredTool]
) -> list[AgentToolUsage]:
    """Observed tools by call count, then configured tools the agent has not called yet."""
    runs_called: dict[tuple[str, str], int] = {}
    call_count: dict[tuple[str, str], int] = {}
    error_count: dict[tuple[str, str], int] = {}
    durations: dict[tuple[str, str], list[float]] = {}
    first_seen: dict[tuple[str, str], AgentToolCall] = {}
    for run in runs:
        for key in {(call.kind, call.name) for call in run.tool_calls}:
            runs_called[key] = runs_called.get(key, 0) + 1
        for call in run.tool_calls:
            key = (call.kind, call.name)
            first_seen.setdefault(key, call)
            call_count[key] = call_count.get(key, 0) + 1
            if call.status in FAILED_TOOL_STATUSES:
                error_count[key] = error_count.get(key, 0) + 1
            if call.elapsed_ms is not None:
                durations.setdefault(key, []).append(call.elapsed_ms)
    configured_by_key = {(tool.kind, tool.name): tool for tool in configured}
    observed = sorted(call_count, key=lambda key: (-call_count[key], key))
    usage = []
    for key in observed:
        seen = first_seen[key]
        known = configured_by_key.get(key)
        usage.append(
            AgentToolUsage(
                kind=key[0],
                name=key[1],
                label=known.label if known else seen.label,
                server=seen.server,
                configured=known is not None,
                runs_called=runs_called.get(key, 0),
                call_count=call_count[key],
                error_count=error_count.get(key, 0),
                avg_ms=_rounded(_mean(durations.get(key, [])), 1),
            )
        )
    usage.extend(
        AgentToolUsage(
            kind=tool.kind,
            name=tool.name,
            label=tool.label,
            server=None,
            configured=True,
            runs_called=0,
            call_count=0,
            error_count=0,
            avg_ms=None,
        )
        for tool in configured
        if (tool.kind, tool.name) not in call_count
    )
    return usage


def suggest_thresholds(baseline: AgentBaseline) -> AgentThresholds:
    """Bounds 20% above the baseline's p95, so normal variation does not fail a run."""
    if baseline.run_count == 0:
        return AgentThresholds()
    latency = baseline.latency_p95_ms
    tokens = baseline.tokens_p95
    cost = baseline.cost_p95_usd
    return AgentThresholds(
        latency_ms=float(math.ceil(latency * THRESHOLD_HEADROOM / 100) * 100) if latency else None,
        cost_usd=round(cost * THRESHOLD_HEADROOM, 6) if cost else None,
        total_tokens=math.ceil(tokens * THRESHOLD_HEADROOM) if tokens else None,
        tool_calls=baseline.tool_calls_max,
    )


def baseline_to_json(baseline: AgentBaseline, captured_at: datetime) -> dict[str, Any]:
    return {**asdict(baseline), "captured_at": captured_at.isoformat()}


def baseline_from_json(data: Any) -> AgentBaseline:
    if not isinstance(data, dict):
        return AgentBaseline()
    known = AgentBaseline.__dataclass_fields__
    return AgentBaseline(**{key: value for key, value in data.items() if key in known})


def _format_count(value: float) -> str:
    return f"{value:,.0f}"


def _threshold_checks(run: AgentRun, thresholds: AgentThresholds) -> list[CheckResult]:
    checks: list[CheckResult] = []
    bounds: list[tuple[str, str, float | None, float | None, str]] = [
        (
            "latency_ms",
            f"Latency ≤ {_format_count(thresholds.latency_ms or 0)} ms",
            thresholds.latency_ms,
            run.latency_ms,
            f"{_format_count(run.latency_ms)} ms",
        ),
        (
            "cost_usd",
            f"Cost ≤ ${thresholds.cost_usd or 0:.4f}",
            thresholds.cost_usd,
            run.cost_usd,
            f"${run.cost_usd:.4f}" if run.cost_usd is not None else "unpriced model",
        ),
        (
            "total_tokens",
            f"Tokens ≤ {_format_count(thresholds.total_tokens or 0)}",
            thresholds.total_tokens,
            float(run.total_tokens),
            _format_count(run.total_tokens),
        ),
        (
            "tool_calls",
            f"Tool calls ≤ {thresholds.tool_calls or 0}",
            thresholds.tool_calls,
            float(run.tool_count),
            str(run.tool_count),
        ),
    ]
    for key, label, bound, actual, detail in bounds:
        if bound is None:
            continue
        if actual is None:
            status: CheckStatus = "skip"
        else:
            status = "pass" if actual <= bound else "fail"
        checks.append(CheckResult(key, label, "threshold", status, detail))
    return checks


def evaluate_run(
    run: AgentRun,
    assertions: list[ToolExpectation],
    thresholds: AgentThresholds,
) -> RunEvaluation:
    """Check one run; a skipped check (an unpriced model's cost) does not fail it."""
    checks = [
        CheckResult(
            "run",
            "Finishes without error",
            "run",
            "fail" if run.error else "pass",
            run.error[:200] if run.error else None,
        )
    ]
    called = [(call.kind, call.name) for call in run.tool_calls]
    for assertion in assertions:
        times = called.count((assertion.kind, assertion.name))
        target = f"{KIND_LABELS.get(assertion.kind, '')}{assertion.label or assertion.name}"
        if assertion.expect == "called":
            status: CheckStatus = "pass" if times > 0 else "fail"
            label = f"Calls {target}"
        else:
            status = "pass" if times == 0 else "fail"
            label = f"Never calls {target}"
        detail = f"called {times}×" if times else "not called"
        checks.append(
            CheckResult(
                f"tool:{assertion.kind}:{assertion.name}", label, "assertion", status, detail
            )
        )
    checks.extend(_threshold_checks(run, thresholds))
    return RunEvaluation(
        run=run,
        passed=all(check.status != "fail" for check in checks),
        checks=checks,
    )


def _delta(metric: str, baseline: float | None, current: float | None) -> MetricDelta:
    pct = None
    if baseline is not None and current is not None and baseline > 0:
        pct = round((current - baseline) / baseline * 100, 1)
    return MetricDelta(metric=metric, baseline=baseline, current=current, delta_pct=pct)


def build_report(
    runs: list[AgentRun],
    assertions: list[ToolExpectation],
    thresholds: AgentThresholds,
    baseline: AgentBaseline,
) -> AgentReport:
    """Score each run, count every check across runs and compare with the baseline."""
    evaluations = [evaluate_run(run, assertions, thresholds) for run in runs]
    summaries: dict[str, CheckSummary] = {}
    for evaluation in evaluations:
        for check in evaluation.checks:
            prev = summaries.get(check.key) or CheckSummary(
                check.key, check.label, check.kind, 0, 0, 0
            )
            summaries[check.key] = CheckSummary(
                key=prev.key,
                label=prev.label,
                kind=prev.kind,
                passed=prev.passed + (check.status == "pass"),
                failed=prev.failed + (check.status == "fail"),
                skipped=prev.skipped + (check.status == "skip"),
            )
    current = summarize_runs(runs)
    passed_count = sum(1 for evaluation in evaluations if evaluation.passed)
    return AgentReport(
        run_count=len(runs),
        passed_count=passed_count,
        pass_rate=round(passed_count / len(runs) * 100, 1) if runs else None,
        checks=list(summaries.values()),
        current=current,
        deltas=[
            _delta("latency_p95_ms", baseline.latency_p95_ms, current.latency_p95_ms),
            _delta("cost_avg_usd", baseline.cost_avg_usd, current.cost_avg_usd),
            _delta("tokens_avg", baseline.tokens_avg, current.tokens_avg),
            _delta("tool_calls_avg", baseline.tool_calls_avg, current.tool_calls_avg),
        ],
        runs=evaluations,
    )
