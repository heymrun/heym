import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import EvalRun, EvalSuite, EvalTestCase, User
from app.db.session import get_db
from app.models.eval_schemas import (
    EvalRunListResponse,
    EvalRunRenameRequest,
    EvalRunResponse,
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
from app.services import prompt_suite_service as prompt_suites
from app.services.eval_common import EvalNotFoundError
from app.services.eval_service import generate_test_data, optimize_prompt

router = APIRouter()


def _not_found(exc: EvalNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _owned_suite(
    db: AsyncSession, suite_id: uuid.UUID, user_id: uuid.UUID, *, with_test_cases: bool = False
) -> EvalSuite:
    try:
        return await prompt_suites.load_owned_prompt_suite(
            db, suite_id, user_id, with_test_cases=with_test_cases
        )
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/suites", response_model=list[EvalSuiteListResponse])
async def list_suites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EvalSuiteListResponse]:
    """Prompt and agent suites together, most recently updated first."""
    return await prompt_suites.list_all_suites(db, current_user.id)


@router.post("/suites", response_model=EvalSuiteResponse)
async def create_suite(
    body: EvalSuiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalSuiteResponse:
    try:
        suite = await prompt_suites.create_prompt_suite(db, current_user.id, body)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return EvalSuiteResponse.model_validate(suite)


@router.get("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def get_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalSuiteResponse:
    suite = await _owned_suite(db, suite_id, current_user.id, with_test_cases=True)
    return EvalSuiteResponse.model_validate(suite)


@router.patch("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def update_suite(
    suite_id: uuid.UUID,
    body: EvalSuiteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalSuiteResponse:
    suite = await _owned_suite(db, suite_id, current_user.id, with_test_cases=True)
    try:
        suite = await prompt_suites.update_prompt_suite(db, suite, body)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return EvalSuiteResponse.model_validate(suite)


@router.delete("/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    suite = await _owned_suite(db, suite_id, current_user.id)
    await db.delete(suite)
    await db.commit()


@router.post("/suites/{suite_id}/test-cases", response_model=EvalTestCaseResponse)
async def add_test_case(
    suite_id: uuid.UUID,
    body: EvalTestCaseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalTestCaseResponse:
    await _owned_suite(db, suite_id, current_user.id)
    tc = await prompt_suites.add_test_case(db, suite_id, body)
    return EvalTestCaseResponse.model_validate(tc)


@router.patch("/suites/{suite_id}/test-cases/{tc_id}", response_model=EvalTestCaseResponse)
async def update_test_case(
    suite_id: uuid.UUID,
    tc_id: uuid.UUID,
    body: EvalTestCaseUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalTestCaseResponse:
    try:
        tc = await prompt_suites.update_test_case(db, suite_id, tc_id, current_user.id, body)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc
    return EvalTestCaseResponse.model_validate(tc)


@router.delete("/suites/{suite_id}/test-cases/{tc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    suite_id: uuid.UUID,
    tc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await prompt_suites.delete_test_case(db, suite_id, tc_id, current_user.id)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/suites/{suite_id}/optimize-prompt", response_model=OptimizePromptResponse)
async def optimize_suite_prompt(
    suite_id: uuid.UUID,
    body: OptimizePromptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OptimizePromptResponse:
    await _owned_suite(db, suite_id, current_user.id)
    try:
        optimized = await optimize_prompt(
            db=db,
            credential_id=uuid.UUID(str(body.credential_id)),
            model=body.model,
            system_prompt=body.system_prompt,
            current_user=current_user,
        )
    except ValueError as e:
        raise _bad_request(e) from e
    return OptimizePromptResponse(optimized_prompt=optimized)


@router.post("/suites/{suite_id}/generate-test-data", response_model=GenerateTestDataResponse)
async def generate_suite_test_data(
    suite_id: uuid.UUID,
    body: GenerateTestDataRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenerateTestDataResponse:
    suite = await _owned_suite(db, suite_id, current_user.id)
    try:
        cases = await generate_test_data(
            db=db,
            credential_id=uuid.UUID(str(body.credential_id)),
            model=body.model,
            system_prompt=suite.system_prompt,
            count=body.count,
            current_user=current_user,
        )
    except ValueError as e:
        raise _bad_request(e) from e
    start = await prompt_suites.next_order_index(db, suite_id)
    created = []
    for i, c in enumerate(cases):
        tc = EvalTestCase(
            suite_id=suite_id,
            input=c.get("input", ""),
            expected_output=c.get("expected_output", ""),
            input_mode=c.get("input_mode", "text"),
            expected_mode=c.get("expected_mode", "text"),
            order_index=start + i,
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
    try:
        launch = await prompt_suites.launch_prompt_run(db, current_user, suite_id, body)
    except ValueError as e:
        raise _bad_request(e) from e
    background_tasks.add_task(launch.job.func, **launch.job.kwargs)
    return prompt_suites.prompt_run_response(launch.run)


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
async def get_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvalRunResponse:
    try:
        run = await prompt_suites.load_owned_prompt_run(db, run_id, current_user.id)
    except EvalNotFoundError as exc:
        raise _not_found(exc) from exc
    return prompt_suites.prompt_run_response(run, run.results or [])


@router.get("/suites/{suite_id}/runs", response_model=list[EvalRunListResponse])
async def list_runs(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EvalRunListResponse]:
    return await prompt_suites.list_prompt_runs(db, suite_id, current_user.id)


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
