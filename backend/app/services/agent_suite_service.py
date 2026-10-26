"""Agent eval suites: the one implementation the Evals routes and the chat tools share."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentSuite, AgentSuiteRun, Workflow
from app.models.agent_suite_schemas import (
    AgentBaselineResponse,
    AgentBaselineSource,
    AgentCheckResultResponse,
    AgentCheckSummaryResponse,
    AgentMetricDeltaResponse,
    AgentMetricsResponse,
    AgentRunEvaluationResponse,
    AgentRunResponse,
    AgentSuiteCreate,
    AgentSuiteReportResponse,
    AgentSuiteResponse,
    AgentSuiteRunInputsResponse,
    AgentSuiteUpdate,
    AgentThresholdsModel,
    AgentToolUsageResponse,
    ToolAssertion,
)
from app.services.agent_suite_inputs import previous_run_inputs
from app.services.agent_suite_metrics import (
    DEFAULT_RUN_LIMIT,
    AgentBaseline,
    AgentThresholds,
    ToolExpectation,
    agent_node_label,
    baseline_from_json,
    baseline_to_json,
    build_report,
    configured_tools,
    find_agent_node,
    load_agent_runs,
    suggest_thresholds,
    summarize_runs,
    summarize_tool_usage,
)
from app.services.eval_common import EvalNotFoundError
from app.services.workflow_access import get_accessible_workflow, workflow_access_clause
from app.services.workflow_inputs import start_input_fields


async def load_accessible_workflow(
    db: AsyncSession, workflow_id: uuid.UUID, user_id: uuid.UUID
) -> Workflow:
    workflow = await get_accessible_workflow(db, workflow_id, user_id)
    if workflow is None:
        raise EvalNotFoundError("Workflow not found")
    return workflow


def require_agent_node(workflow: Workflow, node_id: str) -> dict:
    node = find_agent_node(workflow.nodes, node_id)
    if node is None:
        raise EvalNotFoundError("Agent node not found")
    return node


async def load_owned_agent_suite(
    db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID
) -> AgentSuite:
    result = await db.execute(
        select(AgentSuite).where(AgentSuite.id == suite_id, AgentSuite.owner_id == user_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise EvalNotFoundError("Suite not found")
    return suite


async def load_owned_agent_suite_run(
    db: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID
) -> AgentSuiteRun:
    result = await db.execute(
        select(AgentSuiteRun)
        .join(AgentSuite, AgentSuite.id == AgentSuiteRun.suite_id)
        .where(AgentSuiteRun.id == run_id, AgentSuite.owner_id == user_id)
    )
    suite_run = result.scalar_one_or_none()
    if suite_run is None:
        raise EvalNotFoundError("Run not found")
    return suite_run


async def latest_agent_suite_run(db: AsyncSession, suite_id: uuid.UUID) -> AgentSuiteRun | None:
    result = await db.execute(
        select(AgentSuiteRun)
        .where(AgentSuiteRun.suite_id == suite_id)
        .order_by(AgentSuiteRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def suite_run_trace_ids(suite_run: AgentSuiteRun) -> list[uuid.UUID]:
    """The agent traces one suite run recorded, in run order."""
    return [
        uuid.UUID(trace_id)
        for result in suite_run.results
        for trace_id in result.get("trace_ids") or []
    ]


def input_keys(workflow: Workflow) -> list[str]:
    """The keys of the workflow's start input fields."""
    return [
        field["key"] for field in start_input_fields(workflow.nodes, workflow.edges) if field["key"]
    ]


def _stored_assertions(assertions: list[ToolAssertion]) -> list[dict]:
    """One entry per tool; a later entry for the same tool replaces an earlier one."""
    by_key: dict[tuple[str, str], dict] = {}
    for assertion in assertions:
        name = assertion.name.strip()
        if name:
            by_key[(assertion.kind, name)] = {**assertion.model_dump(), "name": name}
    return list(by_key.values())


async def _sub_workflow_names(db: AsyncSession, node: dict, user_id: uuid.UUID) -> dict[str, str]:
    """Names of the sub-workflows an agent may call, among those the user can reach."""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    ids = []
    for raw in data.get("subWorkflowIds") or []:
        try:
            ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = await db.execute(
        select(Workflow.id, Workflow.name).where(
            Workflow.id.in_(ids), workflow_access_clause(user_id)
        )
    )
    return {str(row.id): row.name for row in rows.all()}


def suite_response(suite: AgentSuite, workflow_name: str) -> AgentSuiteResponse:
    return AgentSuiteResponse(
        id=suite.id,
        name=suite.name,
        workflow_id=suite.workflow_id,
        workflow_name=workflow_name,
        node_id=suite.node_id,
        node_label=suite.node_label,
        tool_assertions=[ToolAssertion.model_validate(item) for item in suite.tool_assertions],
        thresholds=AgentThresholdsModel.model_validate(suite.thresholds or {}),
        baseline=AgentBaselineResponse.model_validate(suite.baseline or {}),
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )


async def agent_metrics(
    db: AsyncSession,
    user_id: uuid.UUID,
    workflow_id: uuid.UUID,
    node_id: str,
    limit: int = DEFAULT_RUN_LIMIT,
) -> AgentMetricsResponse:
    """An agent's latest runs with latency, cost, tokens and tool calls, plus the baseline
    and the thresholds suggested from it."""
    workflow = await load_accessible_workflow(db, workflow_id, user_id)
    node = require_agent_node(workflow, node_id)
    runs = await load_agent_runs(
        db, user_id=user_id, workflow_id=workflow.id, node_id=node_id, limit=limit
    )
    baseline = summarize_runs(runs)
    return AgentMetricsResponse(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        node_id=node_id,
        node_label=agent_node_label(node),
        runs=[AgentRunResponse.model_validate(run) for run in runs],
        baseline=AgentBaselineResponse.model_validate(baseline),
        tools=[
            AgentToolUsageResponse.model_validate(usage)
            for usage in summarize_tool_usage(
                runs, configured_tools(node, await _sub_workflow_names(db, node, user_id))
            )
        ],
        suggested_thresholds=AgentThresholdsModel.model_validate(suggest_thresholds(baseline)),
    )


async def resolve_baseline(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    workflow_id: uuid.UUID,
    node_id: str,
    suite_id: uuid.UUID | None,
    source: AgentBaselineSource,
) -> dict[str, Any]:
    """The baseline JSON a suite stores, measured from runs or taken from stated values.

    ``suite_id`` is None while the suite is being created, so it has no runs to use yet.
    """
    now = datetime.now(timezone.utc)
    if source.source == "manual" and source.values is not None:
        stated = AgentBaseline(**source.values.model_dump())
        return {**baseline_to_json(stated, now), "source": "manual", "suite_run_id": None}
    if source.source == "suite_run" and source.run_id is not None:
        if suite_id is None:
            raise ValueError(
                "A new suite has no runs yet. Create it, run it, then use that run as its baseline."
            )
        suite_run = await db.get(AgentSuiteRun, source.run_id)
        if suite_run is None or suite_run.suite_id != suite_id:
            raise EvalNotFoundError("Run not found")
        if suite_run.status == "running":
            raise ValueError(
                "That run is still going. Use it as the baseline once it has finished."
            )
        trace_ids = suite_run_trace_ids(suite_run)
        if not trace_ids:
            raise ValueError(
                "That run recorded no runs of this agent, so it has nothing to measure."
            )
        runs = await load_agent_runs(
            db, user_id=user_id, workflow_id=workflow_id, node_id=node_id, trace_ids=trace_ids
        )
        return {
            **baseline_to_json(summarize_runs(runs), now),
            "source": "suite_run",
            "suite_run_id": str(suite_run.id),
        }
    runs = await load_agent_runs(db, user_id=user_id, workflow_id=workflow_id, node_id=node_id)
    return {
        **baseline_to_json(summarize_runs(runs), now),
        "source": "latest_runs",
        "suite_run_id": None,
    }


async def get_agent_suite(
    db: AsyncSession, user_id: uuid.UUID, suite_id: uuid.UUID
) -> AgentSuiteResponse:
    suite = await load_owned_agent_suite(db, suite_id, user_id)
    workflow = await load_accessible_workflow(db, suite.workflow_id, user_id)
    return suite_response(suite, workflow.name)


async def create_agent_suite(
    db: AsyncSession, user_id: uuid.UUID, body: AgentSuiteCreate
) -> AgentSuiteResponse:
    """Create a suite for one agent node, with the baseline ``body.baseline`` names."""
    workflow = await load_accessible_workflow(db, body.workflow_id, user_id)
    node = require_agent_node(workflow, body.node_id)
    baseline = await resolve_baseline(
        db,
        user_id,
        workflow_id=workflow.id,
        node_id=body.node_id,
        suite_id=None,
        source=body.baseline,
    )
    suite = AgentSuite(
        owner_id=user_id,
        name=body.name,
        workflow_id=workflow.id,
        node_id=body.node_id,
        node_label=agent_node_label(node),
        tool_assertions=_stored_assertions(body.tool_assertions),
        thresholds=body.thresholds.model_dump(),
        baseline=baseline,
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return suite_response(suite, workflow.name)


async def update_agent_suite(
    db: AsyncSession, user_id: uuid.UUID, suite_id: uuid.UUID, body: AgentSuiteUpdate
) -> AgentSuiteResponse:
    """Apply the fields ``body`` sets. The baseline is resolved first, so a refused baseline
    leaves every other field as it was."""
    suite = await load_owned_agent_suite(db, suite_id, user_id)
    workflow = await load_accessible_workflow(db, suite.workflow_id, user_id)
    source = body.baseline or (AgentBaselineSource() if body.refresh_baseline else None)
    baseline = None
    if source is not None:
        baseline = await resolve_baseline(
            db,
            user_id,
            workflow_id=workflow.id,
            node_id=suite.node_id,
            suite_id=suite.id,
            source=source,
        )
    if body.name is not None:
        suite.name = body.name
    if body.tool_assertions is not None:
        suite.tool_assertions = _stored_assertions(body.tool_assertions)
    if body.thresholds is not None:
        suite.thresholds = body.thresholds.model_dump()
    if baseline is not None:
        node = find_agent_node(workflow.nodes, suite.node_id)
        if node is not None:
            suite.node_label = agent_node_label(node)
        suite.baseline = baseline
    await db.commit()
    await db.refresh(suite)
    return suite_response(suite, workflow.name)


async def agent_suite_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    suite_id: uuid.UUID,
    limit: int = DEFAULT_RUN_LIMIT,
    run_id: uuid.UUID | None = None,
) -> AgentSuiteReportResponse:
    """The suite's assertions and thresholds applied to the agent's latest runs, or to the
    runs one suite run started, with each check's pass count and the drift from the
    stored baseline."""
    suite = await load_owned_agent_suite(db, suite_id, user_id)
    workflow = await load_accessible_workflow(db, suite.workflow_id, user_id)
    trace_ids: list[uuid.UUID] | None = None
    if run_id is not None:
        suite_run = await db.get(AgentSuiteRun, run_id)
        if suite_run is None or suite_run.suite_id != suite.id:
            raise EvalNotFoundError("Run not found")
        trace_ids = suite_run_trace_ids(suite_run)
    runs = await load_agent_runs(
        db,
        user_id=user_id,
        workflow_id=workflow.id,
        node_id=suite.node_id,
        limit=limit,
        trace_ids=trace_ids,
    )
    thresholds = AgentThresholdsModel.model_validate(suite.thresholds or {})
    report = build_report(
        runs,
        [
            ToolExpectation(
                item["name"], item["expect"], item.get("kind", "tool"), item.get("label")
            )
            for item in suite.tool_assertions
        ],
        AgentThresholds(**thresholds.model_dump()),
        baseline_from_json(suite.baseline),
    )
    return AgentSuiteReportResponse(
        suite_id=suite.id,
        run_count=report.run_count,
        passed_count=report.passed_count,
        pass_rate=report.pass_rate,
        checks=[AgentCheckSummaryResponse.model_validate(check) for check in report.checks],
        current=AgentBaselineResponse.model_validate(report.current),
        baseline=AgentBaselineResponse.model_validate(suite.baseline or {}),
        deltas=[AgentMetricDeltaResponse.model_validate(delta) for delta in report.deltas],
        runs=[
            AgentRunEvaluationResponse(
                **AgentRunResponse.model_validate(evaluation.run).model_dump(),
                passed=evaluation.passed,
                checks=[
                    AgentCheckResultResponse.model_validate(check) for check in evaluation.checks
                ],
            )
            for evaluation in report.runs
        ],
    )


async def agent_run_inputs(
    db: AsyncSession, user_id: uuid.UUID, suite_id: uuid.UUID
) -> AgentSuiteRunInputsResponse:
    """The workflow's input fields, filled with the values of its most recent run."""
    suite = await load_owned_agent_suite(db, suite_id, user_id)
    workflow = await load_accessible_workflow(db, suite.workflow_id, user_id)
    previous, started_at = await previous_run_inputs(db, workflow.id)
    return AgentSuiteRunInputsResponse(
        fields=input_keys(workflow), previous_inputs=previous, previous_run_at=started_at
    )
