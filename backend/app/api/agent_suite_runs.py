"""Run an agent suite: execute its workflow a chosen number of times, then score those runs."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_suites import accessible_workflow, owned_agent_suite
from app.api.ai_assistant import run_execute_workflow_tool
from app.api.deps import get_current_user
from app.api.workflows import extract_input_fields_from_workflow
from app.db.models import AgentSuite, AgentSuiteRun, User
from app.db.session import get_db
from app.models.agent_suite_schemas import (
    AgentSuiteRunCreate,
    AgentSuiteRunInputsResponse,
    AgentSuiteRunResponse,
)
from app.services.agent_suite_inputs import (
    agent_trace_ids,
    generate_run_inputs,
    previous_run_inputs,
)
from app.services.hitl_service import build_public_base_url
from app.services.workflow_access import get_accessible_workflow

logger = logging.getLogger(__name__)

router = APIRouter()

TRIGGER_SOURCE = "agent_suite"


def _input_keys(workflow: Any) -> list[str]:
    return [field.key for field in extract_input_fields_from_workflow(workflow) if field.key]


async def execute_agent_suite_run(
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    public_base_url: str,
    credential_id: uuid.UUID | None,
    model: str | None,
) -> None:
    """Run the workflow once per input, one after another, recording each agent trace."""
    from app.db.session import async_session_maker

    async with async_session_maker() as db:
        suite_run = await db.get(AgentSuiteRun, run_id)
        if suite_run is None:
            return
        suite = await db.get(AgentSuite, suite_run.suite_id)
        try:
            workflow = (
                await get_accessible_workflow(db, suite.workflow_id, user_id) if suite else None
            )
            if suite is None or workflow is None:
                raise ValueError("Workflow not found")
            inputs_list: list[dict[str, Any]] = list(suite_run.inputs)
            if suite_run.generate_inputs and credential_id is not None and model:
                previous, _started_at = await previous_run_inputs(db, workflow.id)
                inputs_list = await generate_run_inputs(
                    db,
                    user_id=user_id,
                    credential_id=credential_id,
                    model=model,
                    workflow_name=workflow.name,
                    fields=_input_keys(workflow),
                    example=(inputs_list[0] if inputs_list else None) or previous or {},
                    count=suite_run.requested_count,
                    session_id=str(suite_run.id),
                )
                suite_run.inputs = inputs_list
                await db.commit()
            for inputs in inputs_list:
                raw = await run_execute_workflow_tool(
                    db,
                    user_id,
                    str(workflow.id),
                    inputs,
                    public_base_url,
                    # Each run is its own conversation for OpenCode prompt caching.
                    llm_session_id=str(uuid.uuid4()),
                    trigger_source=TRIGGER_SOURCE,
                )
                try:
                    outcome = json.loads(raw)
                except json.JSONDecodeError:
                    outcome = {"status": "error", "error": "The run returned no readable result."}
                suite_run.results = [
                    *suite_run.results,
                    {
                        "execution_id": outcome.get("execution_history_id"),
                        "status": str(outcome.get("status") or "error"),
                        "trace_ids": agent_trace_ids(outcome.get("node_results"), suite.node_id),
                        "error": outcome.get("error"),
                    },
                ]
                await db.commit()
            suite_run.status = "completed"
        except Exception as exc:
            logger.exception("Agent suite run %s failed", run_id)
            await db.rollback()
            suite_run = await db.get(AgentSuiteRun, run_id)
            if suite_run is None:
                return
            suite_run.status = "failed"
            suite_run.error = str(exc)[:500]
        suite_run.completed_at = datetime.now(timezone.utc)
        await db.commit()


@router.get("/agent-suites/{suite_id}/run-inputs", response_model=AgentSuiteRunInputsResponse)
async def get_run_inputs(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunInputsResponse:
    """The workflow's input fields, filled with the values of its most recent run."""
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    workflow = await accessible_workflow(db, suite.workflow_id, current_user.id)
    previous, started_at = await previous_run_inputs(db, workflow.id)
    return AgentSuiteRunInputsResponse(
        fields=_input_keys(workflow), previous_inputs=previous, previous_run_at=started_at
    )


@router.post(
    "/agent-suites/{suite_id}/runs",
    response_model=AgentSuiteRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_agent_suite_run(
    suite_id: uuid.UUID,
    body: AgentSuiteRunCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunResponse:
    """Run the workflow ``count`` times in the background, with the given inputs each time or
    with inputs a model writes, and score the agent's runs once they finish."""
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    await accessible_workflow(db, suite.workflow_id, current_user.id)
    running = await db.execute(
        select(AgentSuiteRun.id).where(
            AgentSuiteRun.suite_id == suite.id, AgentSuiteRun.status == "running"
        )
    )
    if running.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This suite is already running"
        )
    suite_run = AgentSuiteRun(
        suite_id=suite.id,
        status="running",
        requested_count=body.count,
        generate_inputs=body.generate_inputs,
        inputs=[] if body.generate_inputs else [body.inputs] * body.count,
        results=[],
    )
    if body.generate_inputs and body.inputs:
        # The edited form is the example the model varies.
        suite_run.inputs = [body.inputs]
    db.add(suite_run)
    await db.commit()
    await db.refresh(suite_run)
    background_tasks.add_task(
        execute_agent_suite_run,
        run_id=suite_run.id,
        user_id=current_user.id,
        public_base_url=build_public_base_url(request),
        credential_id=body.credential_id,
        model=(body.model or "").strip() or None,
    )
    return AgentSuiteRunResponse.model_validate(suite_run)


@router.get("/agent-suites/{suite_id}/runs/latest", response_model=AgentSuiteRunResponse | None)
async def get_latest_agent_suite_run(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunResponse | None:
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    result = await db.execute(
        select(AgentSuiteRun)
        .where(AgentSuiteRun.suite_id == suite.id)
        .order_by(AgentSuiteRun.created_at.desc())
        .limit(1)
    )
    suite_run = result.scalar_one_or_none()
    return AgentSuiteRunResponse.model_validate(suite_run) if suite_run else None


@router.get("/agent-suite-runs/{run_id}", response_model=AgentSuiteRunResponse)
async def get_agent_suite_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunResponse:
    result = await db.execute(
        select(AgentSuiteRun)
        .join(AgentSuite, AgentSuite.id == AgentSuiteRun.suite_id)
        .where(AgentSuiteRun.id == run_id, AgentSuite.owner_id == current_user.id)
    )
    suite_run = result.scalar_one_or_none()
    if suite_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return AgentSuiteRunResponse.model_validate(suite_run)
