"""Agent Suite: an agent node's real runs checked against tool assertions and thresholds."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import AgentSuite, User
from app.db.session import get_db
from app.models.agent_suite_schemas import (
    AgentCandidateResponse,
    AgentMetricsResponse,
    AgentSuiteCreate,
    AgentSuiteReportResponse,
    AgentSuiteResponse,
    AgentSuiteUpdate,
)
from app.services import agent_suite_service as agent_suites
from app.services.agent_suite_metrics import DEFAULT_RUN_LIMIT, MAX_RUN_LIMIT, list_agent_nodes
from app.services.eval_common import EvalNotFoundError

router = APIRouter()


def _not_found(exc: EvalNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def owned_agent_suite(
    db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID
) -> AgentSuite:
    try:
        return await agent_suites.load_owned_agent_suite(db, suite_id, user_id)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc


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
    try:
        return await agent_suites.agent_metrics(db, current_user.id, workflow_id, node_id, limit)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/agent-suites", response_model=AgentSuiteResponse, status_code=status.HTTP_201_CREATED
)
async def create_agent_suite(
    body: AgentSuiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteResponse:
    """Create a suite for one agent node; its baseline is the agent's latest runs unless
    ``baseline`` says otherwise."""
    try:
        return await agent_suites.create_agent_suite(db, current_user.id, body)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/agent-suites/{suite_id}", response_model=AgentSuiteResponse)
async def get_agent_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteResponse:
    try:
        return await agent_suites.get_agent_suite(db, current_user.id, suite_id)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/agent-suites/{suite_id}", response_model=AgentSuiteResponse)
async def update_agent_suite(
    suite_id: uuid.UUID,
    body: AgentSuiteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteResponse:
    try:
        return await agent_suites.update_agent_suite(db, current_user.id, suite_id, body)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


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
    try:
        return await agent_suites.agent_suite_report(db, current_user.id, suite_id, limit, run_id)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc
