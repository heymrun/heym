import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.models import EvalRun, EvalSuite, EvalTestCase, User
from app.db.session import get_db
from app.models.eval_schemas import (
    EvalRunListResponse,
    EvalRunRenameRequest,
    EvalRunResponse,
    EvalRunResultResponse,
    EvalSuiteCreate,
    EvalSuiteListResponse,
    EvalSuiteResponse,
    EvalSuiteUpdate,
    EvalTestCaseCreate,
    EvalTestCaseResponse,
    EvalTestCaseUpdate,
    GenerateTestDataRequest,
    GenerateTestDataResponse,
    OptimizePromptRequest,
    OptimizePromptResponse,
    RunEvalsRequest,
)
from app.services.eval_service import generate_test_data, optimize_prompt

router = APIRouter()


@router.get("/suites", response_model=list[EvalSuiteListResponse])
async def list_suites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EvalSuiteListResponse]:
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.owner_id == current_user.id)
        .order_by(EvalSuite.updated_at.desc())
    )
    suites = result.scalars().all()
    return [EvalSuiteListResponse.model_validate(s) for s in suites]


@router.post("/suites", response_model=EvalSuiteResponse)
async def create_suite(
    body: EvalSuiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalSuiteResponse:
    suite = EvalSuite(
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        scoring_method=body.scoring_method,
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    # Re-fetch with test_cases eager-loaded to avoid lazy-load in model_validate
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.id == suite.id)
        .options(selectinload(EvalSuite.test_cases))
    )
    suite_loaded = result.scalar_one()
    return EvalSuiteResponse.model_validate(suite_loaded)


@router.get("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def get_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalSuiteResponse:
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
        .options(selectinload(EvalSuite.test_cases))
    )
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    return EvalSuiteResponse.model_validate(suite)


@router.patch("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def update_suite(
    suite_id: uuid.UUID,
    body: EvalSuiteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalSuiteResponse:
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
        .options(selectinload(EvalSuite.test_cases))
    )
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
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
    return EvalSuiteResponse.model_validate(suite)


@router.delete("/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(EvalSuite).where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
    )
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    await db.delete(suite)
    await db.commit()


@router.post("/suites/{suite_id}/test-cases", response_model=EvalTestCaseResponse)
async def add_test_case(
    suite_id: uuid.UUID,
    body: EvalTestCaseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalTestCaseResponse:
    result = await db.execute(
        select(EvalSuite).where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
    )
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    max_idx_result = await db.execute(
        select(func.coalesce(func.max(EvalTestCase.order_index), -1)).where(
            EvalTestCase.suite_id == suite_id
        )
    )
    max_idx = max_idx_result.scalar() or -1
    order_index = max_idx + 1
    tc = EvalTestCase(
        suite_id=suite_id,
        input=body.input,
        expected_output=body.expected_output,
        input_mode=body.input_mode,
        expected_mode=body.expected_mode,
        order_index=order_index,
    )
    db.add(tc)
    await db.commit()
    await db.refresh(tc)
    return EvalTestCaseResponse.model_validate(tc)


@router.patch("/suites/{suite_id}/test-cases/{tc_id}", response_model=EvalTestCaseResponse)
async def update_test_case(
    suite_id: uuid.UUID,
    tc_id: uuid.UUID,
    body: EvalTestCaseUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalTestCaseResponse:
    result = await db.execute(
        select(EvalTestCase)
        .where(
            EvalTestCase.id == tc_id,
            EvalTestCase.suite_id == suite_id,
            EvalSuite.owner_id == current_user.id,
        )
        .join(EvalSuite, EvalSuite.id == EvalTestCase.suite_id)
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
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
    await db.commit()
    await db.refresh(tc)
    return EvalTestCaseResponse.model_validate(tc)


@router.delete("/suites/{suite_id}/test-cases/{tc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    suite_id: uuid.UUID,
    tc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(EvalTestCase)
        .where(
            EvalTestCase.id == tc_id,
            EvalTestCase.suite_id == suite_id,
            EvalSuite.owner_id == current_user.id,
        )
        .join(EvalSuite, EvalSuite.id == EvalTestCase.suite_id)
    )
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
    await db.delete(tc)
    await db.commit()


@router.post("/suites/{suite_id}/optimize-prompt", response_model=OptimizePromptResponse)
async def optimize_suite_prompt(
    suite_id: uuid.UUID,
    body: OptimizePromptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OptimizePromptResponse:
    credential_id = body.credential_id
    model = body.model
    system_prompt = body.system_prompt
    result = await db.execute(
        select(EvalSuite).where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    try:
        optimized = await optimize_prompt(
            db=db,
            credential_id=uuid.UUID(str(credential_id)),
            model=model,
            system_prompt=system_prompt,
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return OptimizePromptResponse(optimized_prompt=optimized)


@router.post("/suites/{suite_id}/generate-test-data", response_model=GenerateTestDataResponse)
async def generate_suite_test_data(
    suite_id: uuid.UUID,
    body: GenerateTestDataRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenerateTestDataResponse:
    credential_id = body.credential_id
    model = body.model
    result = await db.execute(
        select(EvalSuite).where(EvalSuite.id == suite_id, EvalSuite.owner_id == current_user.id)
    )
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    from app.models.eval_schemas import EvalTestCaseCreate

    try:
        cases = await generate_test_data(
            db=db,
            credential_id=uuid.UUID(str(credential_id)),
            model=model,
            system_prompt=suite.system_prompt,
            count=body.count,
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    max_idx_result = await db.execute(
        select(func.coalesce(func.max(EvalTestCase.order_index), -1)).where(
            EvalTestCase.suite_id == suite_id
        )
    )
    max_idx = max_idx_result.scalar() or -1
    created = []
    for i, c in enumerate(cases):
        tc = EvalTestCase(
            suite_id=suite_id,
            input=c.get("input", ""),
            expected_output=c.get("expected_output", ""),
            input_mode=c.get("input_mode", "text"),
            expected_mode=c.get("expected_mode", "text"),
            order_index=max_idx + 1 + i,
        )
        db.add(tc)
        created.append(EvalTestCaseCreate(**c))
    await db.commit()
    return GenerateTestDataResponse(test_cases=created)


@router.post("/suites/{suite_id}/run", response_model=EvalRunResponse)
async def start_run(
    suite_id: uuid.UUID,
    body: RunEvalsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunResponse:
    from app.services.eval_service import create_run, execute_evals_for_run

    try:
        run = await create_run(
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
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    background_tasks.add_task(
        execute_evals_for_run,
        run_id=run.id,
        credential_id=body.credential_id,
        models=body.models,
        scoring_method=body.scoring_method,
        temperature=body.temperature,
        reasoning_effort=body.reasoning_effort,
        max_tokens=body.max_tokens,
        runs_per_test=body.runs_per_test,
        judge_credential_id=body.judge_credential_id,
        judge_model=body.judge_model,
        user_id=current_user.id,
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
        status=run.status,
        created_at=run.created_at,
        completed_at=run.completed_at,
        results=[],
    )


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
async def get_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunResponse:
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.id == run_id, EvalSuite.owner_id == current_user.id)
        .options(selectinload(EvalRun.results))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    results_list = run.results or []
    results_list = sorted(
        results_list,
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
        status=run.status,
        created_at=run.created_at,
        completed_at=run.completed_at,
        results=[EvalRunResultResponse.model_validate(r) for r in results_list],
    )


@router.get("/suites/{suite_id}/runs", response_model=list[EvalRunListResponse])
async def list_runs(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EvalRunListResponse]:
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.suite_id == suite_id, EvalSuite.owner_id == current_user.id)
        .options(selectinload(EvalRun.results))
        .order_by(EvalRun.created_at.desc())
    )
    runs = result.scalars().all()

    def _score_to_pct(s: str) -> int:
        if s in ("pass",):
            return 100
        if s in ("fail",):
            return 0
        if s in ("partial",):
            return 50
        try:
            return max(0, min(100, int(s)))
        except (ValueError, TypeError):
            return 0

    out = []
    for run in runs:
        results = run.results or []
        total = len(results)
        pass_count = sum(1 for r in results if _score_to_pct(r.score) >= 50)
        out.append(
            EvalRunListResponse(
                id=run.id,
                name=run.name,
                models=run.models or [],
                status=run.status,
                scoring_method=run.scoring_method or "exact_match",
                created_at=run.created_at,
                completed_at=run.completed_at,
                pass_count=pass_count,
                total_count=total,
            )
        )
    return out


@router.patch("/runs/{run_id}")
async def rename_run(
    run_id: uuid.UUID,
    body: EvalRunRenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.id == run_id, EvalSuite.owner_id == current_user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    run.name = body.name
    await db.commit()
    return {"name": run.name}


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.id == run_id, EvalSuite.owner_id == current_user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await db.delete(run)
    await db.commit()


@router.delete("/suites/{suite_id}/runs", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_runs(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalRun.suite_id == suite_id, EvalSuite.owner_id == current_user.id)
    )
    runs = result.scalars().all()
    for run in runs:
        await db.delete(run)
    await db.commit()
