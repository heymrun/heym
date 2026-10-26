"""Prompt eval suites: the one implementation the Evals routes and the chat tools share."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AgentSuite, EvalRun, EvalRunResult, EvalSuite, EvalTestCase, User
from app.models.eval_schemas import (
    EvalRunListResponse,
    EvalRunResponse,
    EvalRunResultResponse,
    EvalSuiteCreate,
    EvalSuiteListResponse,
    EvalSuiteUpdate,
    EvalTestCaseCreate,
    EvalTestCaseUpdate,
    EvalTestCaseUpsert,
    RunEvalsRequest,
)
from app.services import eval_service
from app.services.eval_common import DeferredJob, EvalNotFoundError

SCORING_METHODS = (
    eval_service.SCORING_EXACT_MATCH,
    eval_service.SCORING_CONTAINS,
    eval_service.SCORING_LLM_JUDGE,
)
# A result scoring at least this many percent counts as passed in run lists and summaries.
PASS_PCT = 50

SuiteType = Literal["prompt", "agent"]


@dataclass(frozen=True)
class PromptRunLaunch:
    """A created run row and the job that fills it."""

    run: EvalRun
    job: DeferredJob


def score_to_pct(score: str) -> int:
    """A stored score as 0-100: pass, partial and fail, or a judge's number."""
    if score == "pass":
        return 100
    if score == "fail":
        return 0
    if score == "partial":
        return 50
    try:
        return max(0, min(100, int(score)))
    except (ValueError, TypeError):
        return 0


def is_passing(score: str) -> bool:
    return score_to_pct(score) >= PASS_PCT


def check_scoring_method(method: str | None) -> None:
    """Refuse a scoring method the run would not know; None leaves the stored one."""
    if method is not None and method not in SCORING_METHODS:
        raise ValueError(f"Scoring method must be one of {', '.join(SCORING_METHODS)}")


async def list_all_suites(db: AsyncSession, user_id: uuid.UUID) -> list[EvalSuiteListResponse]:
    """Prompt and agent suites together, most recently updated first."""
    prompt_rows = await db.execute(
        select(
            EvalSuite.id,
            EvalSuite.name,
            EvalSuite.description,
            EvalSuite.created_at,
            EvalSuite.updated_at,
        ).where(EvalSuite.owner_id == user_id)
    )
    agent_rows = await db.execute(
        select(AgentSuite.id, AgentSuite.name, AgentSuite.created_at, AgentSuite.updated_at).where(
            AgentSuite.owner_id == user_id
        )
    )
    entries = [
        (row.updated_at, EvalSuiteListResponse(**row._asdict(), suite_type="prompt"))
        for row in prompt_rows.all()
    ]
    entries.extend(
        (
            row.updated_at,
            EvalSuiteListResponse(
                id=row.id,
                name=row.name,
                description=None,
                created_at=row.created_at,
                suite_type="agent",
            ),
        )
        for row in agent_rows.all()
    )
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    entries.sort(key=lambda entry: entry[0] or oldest, reverse=True)
    return [suite for _updated_at, suite in entries]


async def owned_suite_type(db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID) -> SuiteType:
    """Which kind of suite ``suite_id`` is, among the user's own."""
    prompt = await db.execute(
        select(EvalSuite.id).where(EvalSuite.id == suite_id, EvalSuite.owner_id == user_id)
    )
    if prompt.first() is not None:
        return "prompt"
    agent = await db.execute(
        select(AgentSuite.id).where(AgentSuite.id == suite_id, AgentSuite.owner_id == user_id)
    )
    if agent.first() is not None:
        return "agent"
    raise EvalNotFoundError("Suite not found")


async def owned_suite_name(db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """The name of one of the user's suites, prompt or agent; None when it is not theirs."""
    for model in (EvalSuite, AgentSuite):
        row = (
            await db.execute(
                select(model.name).where(model.id == suite_id, model.owner_id == user_id)
            )
        ).first()
        if row is not None:
            return row.name
    return None


async def load_owned_prompt_suite(
    db: AsyncSession,
    suite_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    with_test_cases: bool = False,
) -> EvalSuite:
    query = select(EvalSuite).where(EvalSuite.id == suite_id, EvalSuite.owner_id == user_id)
    if with_test_cases:
        # populate_existing: a suite changed earlier in this session shows its current cases.
        query = query.options(selectinload(EvalSuite.test_cases)).execution_options(
            populate_existing=True
        )
    suite = (await db.execute(query)).scalar_one_or_none()
    if suite is None:
        raise EvalNotFoundError("Suite not found")
    return suite


async def create_prompt_suite(
    db: AsyncSession, user_id: uuid.UUID, body: EvalSuiteCreate
) -> EvalSuite:
    """Create an empty suite; returns it with its (empty) test cases loaded."""
    check_scoring_method(body.scoring_method)
    suite = EvalSuite(
        owner_id=user_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        scoring_method=body.scoring_method,
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    # Re-fetch with test_cases eager-loaded to avoid a lazy load in model_validate.
    return await load_owned_prompt_suite(db, suite.id, user_id, with_test_cases=True)


async def update_prompt_suite(
    db: AsyncSession, suite: EvalSuite, body: EvalSuiteUpdate
) -> EvalSuite:
    """Apply the fields ``body`` sets; ``suite`` is loaded with its test cases."""
    check_scoring_method(body.scoring_method)
    if body.name is not None:
        suite.name = body.name
    if body.description is not None:
        suite.description = body.description
    if body.system_prompt is not None:
        suite.system_prompt = body.system_prompt
    if body.scoring_method is not None:
        suite.scoring_method = body.scoring_method
    await db.commit()
    await db.refresh(suite)
    return suite


async def next_order_index(db: AsyncSession, suite_id: uuid.UUID) -> int:
    """The order_index after the suite's last test case, 0 for an empty suite."""
    result = await db.execute(
        select(func.coalesce(func.max(EvalTestCase.order_index), -1)).where(
            EvalTestCase.suite_id == suite_id
        )
    )
    return result.scalar() + 1


async def add_test_case(
    db: AsyncSession, suite_id: uuid.UUID, body: EvalTestCaseCreate
) -> EvalTestCase:
    """Append a case to a suite the caller has already checked."""
    tc = EvalTestCase(
        suite_id=suite_id,
        input=body.input,
        expected_output=body.expected_output,
        input_mode=body.input_mode,
        expected_mode=body.expected_mode,
        order_index=await next_order_index(db, suite_id),
    )
    db.add(tc)
    await db.commit()
    await db.refresh(tc)
    return tc


async def load_owned_test_case(
    db: AsyncSession, suite_id: uuid.UUID, tc_id: uuid.UUID, user_id: uuid.UUID
) -> EvalTestCase:
    result = await db.execute(
        select(EvalTestCase)
        .where(
            EvalTestCase.id == tc_id,
            EvalTestCase.suite_id == suite_id,
            EvalSuite.owner_id == user_id,
        )
        .join(EvalSuite, EvalSuite.id == EvalTestCase.suite_id)
    )
    tc = result.scalar_one_or_none()
    if tc is None:
        raise EvalNotFoundError("Test case not found")
    return tc


def _apply_case_update(tc: EvalTestCase, body: EvalTestCaseUpdate) -> None:
    if body.input is not None:
        tc.input = body.input
    if body.expected_output is not None:
        tc.expected_output = body.expected_output
    if body.input_mode is not None:
        tc.input_mode = body.input_mode
    if body.expected_mode is not None:
        tc.expected_mode = body.expected_mode
    if body.order_index is not None:
        tc.order_index = body.order_index


async def update_test_case(
    db: AsyncSession,
    suite_id: uuid.UUID,
    tc_id: uuid.UUID,
    user_id: uuid.UUID,
    body: EvalTestCaseUpdate,
) -> EvalTestCase:
    tc = await load_owned_test_case(db, suite_id, tc_id, user_id)
    _apply_case_update(tc, body)
    await db.commit()
    await db.refresh(tc)
    return tc


async def delete_test_case(
    db: AsyncSession, suite_id: uuid.UUID, tc_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    tc = await load_owned_test_case(db, suite_id, tc_id, user_id)
    await db.delete(tc)
    await db.commit()


async def apply_test_case_changes(
    db: AsyncSession,
    suite: EvalSuite,
    upserts: list[EvalTestCaseUpsert],
    delete_ids: list[uuid.UUID],
) -> EvalSuite:
    """Add, change and remove cases in one commit; an id outside the suite writes nothing.

    ``suite`` is loaded with its test cases. Returns it reloaded with the result.
    """
    existing = {tc.id: tc for tc in suite.test_cases}
    named = [*(upsert.id for upsert in upserts if upsert.id is not None), *delete_ids]
    unknown = [str(tc_id) for tc_id in named if tc_id not in existing]
    if unknown:
        raise ValueError(f"Not a test case of this suite: {', '.join(unknown)}")
    order_index = await next_order_index(db, suite.id)
    for upsert in upserts:
        if upsert.id is not None:
            _apply_case_update(existing[upsert.id], upsert)
            continue
        db.add(
            EvalTestCase(
                suite_id=suite.id,
                input=upsert.input or "",
                expected_output=upsert.expected_output or "",
                input_mode=upsert.input_mode or "text",
                expected_mode=upsert.expected_mode or "text",
                order_index=order_index,
            )
        )
        order_index += 1
    for tc_id in delete_ids:
        await db.delete(existing[tc_id])
    await db.commit()
    return await load_owned_prompt_suite(db, suite.id, suite.owner_id, with_test_cases=True)


async def launch_prompt_run(
    db: AsyncSession, user: User, suite_id: uuid.UUID, body: RunEvalsRequest
) -> PromptRunLaunch:
    """Create a run row, refusing a bad suite, credential or judge, and the job that fills it."""
    check_scoring_method(body.scoring_method)
    run = await eval_service.create_run(
        db=db,
        suite_id=suite_id,
        credential_id=body.credential_id,
        models=body.models,
        scoring_method=body.scoring_method,
        temperature=body.temperature,
        reasoning_effort=body.reasoning_effort,
        max_tokens=body.max_tokens,
        runs_per_test=body.runs_per_test,
        judge_credential_id=body.judge_credential_id,
        judge_model=body.judge_model,
        current_user=user,
    )
    job = DeferredJob(
        eval_service.execute_evals_for_run,
        {
            "run_id": run.id,
            "credential_id": body.credential_id,
            "models": body.models,
            "scoring_method": body.scoring_method,
            "temperature": body.temperature,
            "reasoning_effort": body.reasoning_effort,
            "max_tokens": body.max_tokens,
            "runs_per_test": body.runs_per_test,
            "user_id": user.id,
        },
    )
    return PromptRunLaunch(run=run, job=job)


async def load_owned_prompt_run(db: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID) -> EvalRun:
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.id == run_id, EvalSuite.owner_id == user_id)
        .options(selectinload(EvalRun.results))
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise EvalNotFoundError("Run not found")
    return run


def prompt_run_response(
    run: EvalRun, results: list[EvalRunResult] | None = None
) -> EvalRunResponse:
    """The run with its results in run order; a run just started has none to read."""
    ordered = sorted(
        results or [],
        key=lambda r: (r.run_order if r.run_order is not None else 999999, r.created_at),
    )
    return EvalRunResponse(
        id=run.id,
        suite_id=run.suite_id,
        name=run.name,
        system_prompt_snapshot=run.system_prompt_snapshot,
        models=run.models or [],
        scoring_method=run.scoring_method,
        temperature=run.temperature,
        reasoning_effort=run.reasoning_effort,
        max_tokens=run.max_tokens,
        runs_per_test=run.runs_per_test or 1,
        credential_id=run.credential_id,
        judge_credential_id=run.judge_credential_id,
        judge_model=run.judge_model,
        status=run.status,
        created_at=run.created_at,
        completed_at=run.completed_at,
        results=[EvalRunResultResponse.model_validate(r) for r in ordered],
    )


async def list_prompt_runs(
    db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID
) -> list[EvalRunListResponse]:
    """The suite's runs, newest first, with how many results passed."""
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.suite_id == suite_id, EvalSuite.owner_id == user_id)
        .options(selectinload(EvalRun.results))
        .order_by(EvalRun.created_at.desc())
    )
    runs = result.scalars().all()
    return [
        EvalRunListResponse(
            id=run.id,
            name=run.name,
            models=run.models or [],
            credential_id=run.credential_id,
            temperature=run.temperature,
            reasoning_effort=run.reasoning_effort,
            max_tokens=run.max_tokens,
            runs_per_test=run.runs_per_test or 1,
            judge_credential_id=run.judge_credential_id,
            status=run.status,
            scoring_method=run.scoring_method or "exact_match",
            judge_model=run.judge_model,
            created_at=run.created_at,
            completed_at=run.completed_at,
            pass_count=sum(1 for r in run.results or [] if is_passing(r.score)),
            total_count=len(run.results or []),
        )
        for run in runs
    ]
