"""Agent Suite: an agent node's real runs checked against tool assertions and thresholds."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import AgentSuite, AgentSuiteRun, User, Workflow
from app.db.session import get_db
from app.models.agent_suite_schemas import (
    AgentBaselineResponse,
    AgentCandidateResponse,
    AgentCheckResultResponse,
    AgentCheckSummaryResponse,
    AgentMetricDeltaResponse,
    AgentMetricsResponse,
    AgentRunEvaluationResponse,
    AgentRunResponse,
    AgentSuiteCreate,
    AgentSuiteReportResponse,
    AgentSuiteResponse,
    AgentSuiteUpdate,
    AgentThresholdsModel,
    AgentToolUsageResponse,
    ToolAssertion,
)
from app.services.agent_suite_metrics import (
    DEFAULT_RUN_LIMIT,
    MAX_RUN_LIMIT,
    AgentThresholds,
    ToolExpectation,
    agent_node_label,
    baseline_from_json,
    baseline_to_json,
    build_report,
    configured_tools,
    find_agent_node,
    list_agent_nodes,
    load_agent_runs,
    suggest_thresholds,
    summarize_runs,
    summarize_tool_usage,
)
from app.services.workflow_access import get_accessible_workflow, workflow_access_clause

router = APIRouter()


async def accessible_workflow(
    db: AsyncSession, workflow_id: uuid.UUID, user_id: uuid.UUID
) -> Workflow:
    workflow = await get_accessible_workflow(db, workflow_id, user_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


def _agent_node(workflow: Workflow, node_id: str) -> dict:
    node = find_agent_node(workflow.nodes, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent node not found")
    return node


async def owned_agent_suite(
    db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID
) -> AgentSuite:
    result = await db.execute(
        select(AgentSuite).where(AgentSuite.id == suite_id, AgentSuite.owner_id == user_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    return suite


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


def _suite_response(suite: AgentSuite, workflow_name: str) -> AgentSuiteResponse:
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


async def _baseline_snapshot(
    db: AsyncSession, user_id: uuid.UUID, workflow_id: uuid.UUID, node_id: str
) -> dict:
    runs = await load_agent_runs(db, user_id=user_id, workflow_id=workflow_id, node_id=node_id)
    return baseline_to_json(summarize_runs(runs), datetime.now(timezone.utc))


@router.get("/agents", response_model=list[AgentCandidateResponse])
async def list_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentCandidateResponse]:
    """Agent nodes in the caller's workflows with their run counts, for the suite picker."""
    candidates = await list_agent_nodes(db, user_id=current_user.id)
    return [AgentCandidateResponse.model_validate(candidate) for candidate in candidates]


@router.get("/agent-metrics", response_model=AgentMetricsResponse)
async def get_agent_metrics(
    workflow_id: uuid.UUID,
    node_id: str = Query(min_length=1, max_length=64),
    limit: int = Query(DEFAULT_RUN_LIMIT, ge=1, le=MAX_RUN_LIMIT),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentMetricsResponse:
    """An agent's latest runs with latency, cost, tokens and tool calls, plus the baseline
    and the thresholds suggested from it."""
    workflow = await accessible_workflow(db, workflow_id, current_user.id)
    node = _agent_node(workflow, node_id)
    runs = await load_agent_runs(
        db, user_id=current_user.id, workflow_id=workflow.id, node_id=node_id, limit=limit
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
                runs,
                configured_tools(node, await _sub_workflow_names(db, node, current_user.id)),
            )
        ],
        suggested_thresholds=AgentThresholdsModel.model_validate(suggest_thresholds(baseline)),
    )


@router.post(
    "/agent-suites", response_model=AgentSuiteResponse, status_code=status.HTTP_201_CREATED
)
async def create_agent_suite(
    body: AgentSuiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteResponse:
    """Create a suite for one agent node; its baseline is the agent's latest runs."""
    workflow = await accessible_workflow(db, body.workflow_id, current_user.id)
    node = _agent_node(workflow, body.node_id)
    suite = AgentSuite(
        owner_id=current_user.id,
        name=body.name,
        workflow_id=workflow.id,
        node_id=body.node_id,
        node_label=agent_node_label(node),
        tool_assertions=_stored_assertions(body.tool_assertions),
        thresholds=body.thresholds.model_dump(),
        baseline=await _baseline_snapshot(db, current_user.id, workflow.id, body.node_id),
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return _suite_response(suite, workflow.name)


@router.get("/agent-suites/{suite_id}", response_model=AgentSuiteResponse)
async def get_agent_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteResponse:
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    workflow = await accessible_workflow(db, suite.workflow_id, current_user.id)
    return _suite_response(suite, workflow.name)


@router.patch("/agent-suites/{suite_id}", response_model=AgentSuiteResponse)
async def update_agent_suite(
    suite_id: uuid.UUID,
    body: AgentSuiteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteResponse:
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    workflow = await accessible_workflow(db, suite.workflow_id, current_user.id)
    if body.name is not None:
        suite.name = body.name
    if body.tool_assertions is not None:
        suite.tool_assertions = _stored_assertions(body.tool_assertions)
    if body.thresholds is not None:
        suite.thresholds = body.thresholds.model_dump()
    if body.refresh_baseline:
        node = find_agent_node(workflow.nodes, suite.node_id)
        if node is not None:
            suite.node_label = agent_node_label(node)
        suite.baseline = await _baseline_snapshot(db, current_user.id, workflow.id, suite.node_id)
    await db.commit()
    await db.refresh(suite)
    return _suite_response(suite, workflow.name)


@router.delete("/agent-suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    await db.delete(suite)
    await db.commit()


@router.get("/agent-suites/{suite_id}/report", response_model=AgentSuiteReportResponse)
async def get_agent_suite_report(
    suite_id: uuid.UUID,
    limit: int = Query(DEFAULT_RUN_LIMIT, ge=1, le=MAX_RUN_LIMIT),
    run_id: uuid.UUID | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteReportResponse:
    """The suite's assertions and thresholds applied to the agent's latest runs, or to the
    runs one press of Run started, with each check's pass count and the drift from the
    stored baseline."""
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    workflow = await accessible_workflow(db, suite.workflow_id, current_user.id)
    trace_ids: list[uuid.UUID] | None = None
    if run_id is not None:
        suite_run = await db.get(AgentSuiteRun, run_id)
        if suite_run is None or suite_run.suite_id != suite.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        trace_ids = [
            uuid.UUID(trace_id)
            for result in suite_run.results
            for trace_id in result.get("trace_ids") or []
        ]
    runs = await load_agent_runs(
        db,
        user_id=current_user.id,
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
