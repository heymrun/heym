# Eval Suites from Chat and MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Chat tab message or an MCP `heym_chat` call can create, edit and run prompt and agent eval suites. That includes an agent's baseline: reported, built from runs, or entered by hand.

**Architecture:** Suite and run logic moves out of the Evals routers into `prompt_suite_service.py` and `agent_suite_service.py`. The run launch stays in `agent_suite_runs.py`. Routers become thin wrappers, and a new `ChatEvalTools` (`app/api/chat_evals.py`) calls the same functions. `ChatBuildSession` offers those tools on build turns only: the Chat tab, MCP `heym_chat` and Heym Work Chat. They are never offered on skill-only turns or in the canvas assistant, and they never appear in MCP `tools/list`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pytest on unittest with real PostgreSQL, Vue 3 + TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-chat-eval-suites-design.md`

---

## Prerequisites (once per session)

Backend tests in this plan write real rows. Run them against a throwaway PostgreSQL, never the dev database:

```bash
orb start   # OrbStack is this Mac's Docker runtime
docker run --rm -d --name heym-evals-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=heym_evals -p 127.0.0.1:6599:5432 postgres:16
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:6599/heym_evals
export SECRET_KEY=test-secret-key-for-tests-only-32-bytes
export ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
cd backend && uv run alembic upgrade head && cd ..
git checkout -b feat/chat-eval-suites
```

Every `uv run pytest` below runs from `backend/` with these variables exported. Remove the container at the end with `docker rm -f heym-evals-pg`.

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/app/services/eval_common.py` | create | `EvalNotFoundError`, `DeferredJob` (a background job a route queues or the chat starts) |
| `backend/app/models/eval_schemas.py` | modify | `EvalTestCaseUpsert` |
| `backend/app/services/prompt_suite_service.py` | create | prompt suites, test cases, run launch, run responses, the combined suite list |
| `backend/app/api/evals.py` | modify | thin routes over `prompt_suite_service` |
| `backend/app/models/agent_suite_schemas.py` | modify | `AgentBaselineValues`, `AgentBaselineSource`, `source`/`suite_run_id` on the baseline, `baseline` on create/update, `inputs_list` on run create |
| `backend/app/services/agent_suite_service.py` | create | agent suite lookups, metrics, baseline sources, create/update, report, run inputs |
| `backend/app/api/agent_suites.py` | modify | thin routes over `agent_suite_service` |
| `backend/app/api/agent_suite_runs.py` | modify | `launch_agent_suite_run`, `AgentSuiteBusyError`, thin routes |
| `backend/app/api/credentials.py` | modify | `list_credential_models` shared by the route and the chat |
| `backend/app/services/chat_build_mode.py` | modify | `BuildToolOutcome`, `tool_error`, public `truncate_text` |
| `backend/app/services/chat_eval_mode.py` | create | eval tool names, limits, argument parsing, result shapes, instructions (no DB or model access) |
| `backend/app/api/chat_evals.py` | create | `ChatEvalTools`: schemas and the nine tools |
| `backend/app/api/chat_build.py` | modify | offers and delegates the eval tools on build turns |
| `backend/app/services/mcp_chat_service.py` | modify | `heym_chat` description mentions eval suites |
| `frontend/src/types/evals.ts` | modify | new request and response fields |
| `frontend/src/components/Evals/AgentSuite/agentSuiteFormat.ts` | modify | `baselineSourceLabel` |
| `frontend/src/components/Evals/AgentSuite/AgentSuiteChecksStep.vue` | modify | shows the baseline's source |
| docs, `AGENTS.md`, release tour | modify | see Tasks 11 and 12 |

---

### Task 1: Shared eval types and the prompt suite service

**Files:**
- Create: `backend/app/services/eval_common.py`
- Create: `backend/app/services/prompt_suite_service.py`
- Modify: `backend/app/models/eval_schemas.py` (after `EvalTestCaseUpdate`, line 62)
- Test: `backend/tests/test_prompt_suite_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_prompt_suite_service.py`:

```python
"""Prompt suites through the service the Evals routes and the chat tools share.

Requires a reachable PostgreSQL instance with migrations applied.
"""

import unittest
import uuid
from types import SimpleNamespace

from sqlalchemy import delete

from app.db.models import AgentSuite, Credential, CredentialType, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.eval_schemas import (
    EvalSuiteCreate,
    EvalSuiteUpdate,
    EvalTestCaseCreate,
    EvalTestCaseUpdate,
    EvalTestCaseUpsert,
    RunEvalsRequest,
)
from app.services import eval_service
from app.services import prompt_suite_service as prompt_suites
from app.services.eval_common import EvalNotFoundError


class ScoreTests(unittest.TestCase):
    def test_scores_map_to_percent(self) -> None:
        scores = ("pass", "partial", "fail", "73", "250", "x")
        self.assertEqual(
            [prompt_suites.score_to_pct(score) for score in scores], [100, 50, 0, 73, 100, 0]
        )
        self.assertTrue(prompt_suites.is_passing("50"))
        self.assertFalse(prompt_suites.is_passing("49"))

    def test_only_known_scoring_methods_pass(self) -> None:
        prompt_suites.check_scoring_method("llm_judge")
        prompt_suites.check_scoring_method(None)
        with self.assertRaises(ValueError):
            prompt_suites.check_scoring_method("regex")


class RealPostgresPromptSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.credential_id = uuid.uuid4()
        self.outsider_credential_id = uuid.uuid4()
        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"prompt_suite_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name="User",
                    )
                    for user_id in (self.owner_id, self.outsider_id)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Credential(
                        id=self.credential_id,
                        owner_id=self.owner_id,
                        name=f"openai-{self.credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                    Credential(
                        id=self.outsider_credential_id,
                        owner_id=self.outsider_id,
                        name=f"theirs-{self.outsider_credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        user_ids = [self.owner_id, self.outsider_id]
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.owner_id.in_(user_ids)))
            await session.execute(delete(Credential).where(Credential.owner_id.in_(user_ids)))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()

    async def test_create_and_update_check_the_scoring_method(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db,
                self.owner_id,
                EvalSuiteCreate(name="Support", system_prompt="Answer.", scoring_method="contains"),
            )
            self.assertEqual(suite.test_cases, [])
            updated = await prompt_suites.update_prompt_suite(
                db, suite, EvalSuiteUpdate(name="Support v2")
            )
            self.assertEqual((updated.name, updated.scoring_method), ("Support v2", "contains"))
            with self.assertRaises(ValueError):
                await prompt_suites.create_prompt_suite(
                    db, self.owner_id, EvalSuiteCreate(name="Bad", scoring_method="regex")
                )

    async def test_test_case_changes_apply_together(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            first = await prompt_suites.add_test_case(
                db, suite.id, EvalTestCaseCreate(input="1+1", expected_output="2")
            )
            second = await prompt_suites.add_test_case(
                db, suite.id, EvalTestCaseCreate(input="2+2", expected_output="4")
            )
            suite = await prompt_suites.load_owned_prompt_suite(
                db, suite.id, self.owner_id, with_test_cases=True
            )
            suite = await prompt_suites.apply_test_case_changes(
                db,
                suite,
                [
                    EvalTestCaseUpsert(id=first.id, expected_output="two"),
                    EvalTestCaseUpsert(input="3+3", expected_output="6"),
                ],
                [second.id],
            )
        self.assertEqual(
            [(tc.input, tc.expected_output, tc.order_index) for tc in suite.test_cases],
            [("1+1", "two", 0), ("3+3", "6", 2)],
        )

    async def test_an_unknown_test_case_id_writes_nothing(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            await prompt_suites.add_test_case(
                db, suite.id, EvalTestCaseCreate(input="1+1", expected_output="2")
            )
            suite = await prompt_suites.load_owned_prompt_suite(
                db, suite.id, self.owner_id, with_test_cases=True
            )
            with self.assertRaises(ValueError):
                await prompt_suites.apply_test_case_changes(
                    db, suite, [EvalTestCaseUpsert(input="new")], [uuid.uuid4()]
                )
        async with async_session_maker() as db:
            reloaded = await prompt_suites.load_owned_prompt_suite(
                db, suite.id, self.owner_id, with_test_cases=True
            )
        self.assertEqual([tc.input for tc in reloaded.test_cases], ["1+1"])

    async def test_another_user_cannot_reach_the_suite_or_its_cases(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Private")
            )
            case = await prompt_suites.add_test_case(db, suite.id, EvalTestCaseCreate(input="a"))
            for call in (
                prompt_suites.load_owned_prompt_suite(db, suite.id, self.outsider_id),
                prompt_suites.update_test_case(
                    db, suite.id, case.id, self.outsider_id, EvalTestCaseUpdate(input="b")
                ),
                prompt_suites.delete_test_case(db, suite.id, case.id, self.outsider_id),
                prompt_suites.owned_suite_type(db, suite.id, self.outsider_id),
            ):
                with self.assertRaises(EvalNotFoundError):
                    await call

    async def test_suite_types_and_the_combined_list(self) -> None:
        workflow_id = uuid.uuid4()
        async with async_session_maker() as db:
            prompt = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Prompt")
            )
            db.add(Workflow(id=workflow_id, name="Flow", owner_id=self.owner_id, nodes=[], edges=[]))
            await db.flush()
            agent = AgentSuite(
                owner_id=self.owner_id,
                name="Agent",
                workflow_id=workflow_id,
                node_id="agent-1",
                node_label="Agent",
                tool_assertions=[],
                thresholds={},
                baseline={},
            )
            db.add(agent)
            await db.commit()
            self.assertEqual(
                await prompt_suites.owned_suite_type(db, prompt.id, self.owner_id), "prompt"
            )
            self.assertEqual(
                await prompt_suites.owned_suite_type(db, agent.id, self.owner_id), "agent"
            )
            listed = await prompt_suites.list_all_suites(db, self.owner_id)
        self.assertEqual(
            {(item.name, item.suite_type) for item in listed},
            {("Prompt", "prompt"), ("Agent", "agent")},
        )

    async def test_launch_creates_a_running_row_and_its_job(self) -> None:
        owner = SimpleNamespace(id=self.owner_id)
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            launch = await prompt_suites.launch_prompt_run(
                db,
                owner,
                suite.id,
                RunEvalsRequest(credential_id=self.credential_id, models=["gpt-4o"]),
            )
        self.assertEqual(launch.run.status, "running")
        self.assertIs(launch.job.func, eval_service.execute_evals_for_run)
        self.assertEqual(launch.job.kwargs["run_id"], launch.run.id)
        self.assertEqual(launch.job.kwargs["models"], ["gpt-4o"])
        async with async_session_maker() as db:
            run = await prompt_suites.load_owned_prompt_run(db, launch.run.id, self.owner_id)
            with self.assertRaises(EvalNotFoundError):
                await prompt_suites.load_owned_prompt_run(db, launch.run.id, self.outsider_id)
            listed = await prompt_suites.list_prompt_runs(db, suite.id, self.owner_id)
        self.assertEqual(prompt_suites.prompt_run_response(run, run.results).status, "running")
        self.assertEqual([item.id for item in listed], [launch.run.id])

    async def test_launch_refuses_another_users_credential(self) -> None:
        async with async_session_maker() as db:
            suite = await prompt_suites.create_prompt_suite(
                db, self.owner_id, EvalSuiteCreate(name="Math")
            )
            with self.assertRaises(ValueError):
                await prompt_suites.launch_prompt_run(
                    db,
                    SimpleNamespace(id=self.owner_id),
                    suite.id,
                    RunEvalsRequest(credential_id=self.outsider_credential_id, models=["gpt-4o"]),
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_prompt_suite_service.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.prompt_suite_service'`

- [ ] **Step 3: Create `backend/app/services/eval_common.py`**

```python
"""What the prompt and agent suite services share with the routes and the chat tools."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


class EvalNotFoundError(LookupError):
    """A suite, test case, run or workflow the user cannot reach, or that does not exist."""


@dataclass(frozen=True)
class DeferredJob:
    """A background job and its keyword arguments, started once the request has committed.

    A route queues it with ``background_tasks.add_task(job.func, **job.kwargs)``; the chat
    starts ``job.coroutine()`` detached, so the run outlives the turn that started it.
    """

    func: Callable[..., Coroutine[Any, Any, None]]
    kwargs: dict[str, Any] = field(default_factory=dict)

    def coroutine(self) -> Coroutine[Any, Any, None]:
        return self.func(**self.kwargs)
```

- [ ] **Step 4: Add `EvalTestCaseUpsert` to `backend/app/models/eval_schemas.py`**

Insert after the `EvalTestCaseUpdate` class:

```python
class EvalTestCaseUpsert(EvalTestCaseUpdate):
    """A case to change (``id`` of one of the suite's cases) or to add (no ``id``)."""

    id: uuid.UUID | None = None
```

- [ ] **Step 5: Create `backend/app/services/prompt_suite_service.py`**

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_prompt_suite_service.py -v`
Expected: 9 passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/eval_common.py backend/app/services/prompt_suite_service.py \
  backend/app/models/eval_schemas.py backend/tests/test_prompt_suite_service.py
git commit -m "feat(evals): prompt suite service shared by routes and chat"
```

---

### Task 2: Prompt suite routes call the service

**Files:**
- Modify: `backend/app/api/evals.py` (whole file)
- Test: existing `backend/tests/test_eval_order_index.py`, `backend/tests/test_eval_judge.py`, `backend/tests/test_agent_suites_api.py` (they call these routes)

- [ ] **Step 1: Run the existing route tests as the baseline**

Run: `uv run pytest tests/test_eval_order_index.py tests/test_eval_judge.py tests/test_agent_suites_api.py -v`
Expected: all pass (note the count; Step 3 must keep it)

- [ ] **Step 2: Replace `backend/app/api/evals.py`**

Keep `rename_run`, `delete_run` and `clear_all_runs` exactly as they are today (lines 482-534). Replace everything above them with:

```python
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
```

`EvalRunRenameRequest`, `select`, `EvalRun` and `EvalSuite` stay imported because the three run routes kept below use them.

- [ ] **Step 3: Run the route tests and lint**

Run: `uv run pytest tests/test_eval_order_index.py tests/test_eval_judge.py tests/test_agent_suites_api.py tests/test_prompt_suite_service.py -v && uv run ruff check app/api/evals.py app/services/prompt_suite_service.py`
Expected: the same pass count as Step 1 plus 9, and `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/evals.py
git commit -m "refactor(evals): prompt suite routes call the shared service"
```

---

### Task 3: Baseline sources, the agent suite service, and thin agent suite routes

**Files:**
- Modify: `backend/app/models/agent_suite_schemas.py`
- Create: `backend/app/services/agent_suite_service.py`
- Modify: `backend/app/api/agent_suites.py` (whole file)
- Test: `backend/tests/test_agent_suite_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_suite_service.py`:

```python
"""Agent suites through the service the Evals routes and the chat tools share.

The baseline can come from the agent's latest runs, from one finished suite run, or from
numbers the user states. Requires a reachable PostgreSQL instance with migrations applied.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import delete

from app.db.models import AgentSuite, AgentSuiteRun, LLMTrace, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.agent_suite_schemas import (
    AgentBaselineSource,
    AgentBaselineValues,
    AgentSuiteCreate,
    AgentSuiteRunCreate,
    AgentSuiteUpdate,
)
from app.services import agent_suite_service as agent_suites
from app.services.eval_common import EvalNotFoundError

AGENT_NODE = "agent-1"


class AgentBaselineSchemaTests(unittest.TestCase):
    def test_each_source_needs_its_input(self) -> None:
        with self.assertRaises(ValidationError):
            AgentBaselineSource(source="suite_run")
        with self.assertRaises(ValidationError):
            AgentBaselineSource(source="manual")
        with self.assertRaises(ValidationError):
            AgentBaselineValues()
        self.assertEqual(AgentBaselineSource().source, "latest_runs")

    def test_create_refuses_a_suite_run_baseline(self) -> None:
        with self.assertRaises(ValidationError):
            AgentSuiteCreate(
                name="x",
                workflow_id=uuid.uuid4(),
                node_id="a",
                baseline={"source": "suite_run", "run_id": str(uuid.uuid4())},
            )

    def test_update_takes_refresh_or_baseline_not_both(self) -> None:
        with self.assertRaises(ValidationError):
            AgentSuiteUpdate(refresh_baseline=True, baseline={"source": "latest_runs"})

    def test_an_inputs_list_holds_1_to_20_runs_and_excludes_generation(self) -> None:
        with self.assertRaises(ValidationError):
            AgentSuiteRunCreate(
                inputs_list=[{"text": "a"}],
                generate_inputs=True,
                credential_id=uuid.uuid4(),
                model="m",
            )
        with self.assertRaises(ValidationError):
            AgentSuiteRunCreate(inputs_list=[{"text": str(i)} for i in range(21)])
        with self.assertRaises(ValidationError):
            AgentSuiteRunCreate(inputs_list=[])


class RealPostgresAgentSuiteServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.suite_id = uuid.uuid4()
        self.other_suite_id = uuid.uuid4()
        self.finished_run_id = uuid.uuid4()
        self.running_run_id = uuid.uuid4()
        self.empty_run_id = uuid.uuid4()
        self.other_suite_run_id = uuid.uuid4()
        self.suite_run_traces = [uuid.uuid4(), uuid.uuid4()]
        now = datetime.now(timezone.utc)

        def trace(trace_id: uuid.UUID, minutes_ago: int, elapsed_ms: float) -> LLMTrace:
            return LLMTrace(
                id=trace_id,
                user_id=self.owner_id,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                source="workflow",
                request_type="chat.completions",
                model="agent-suite-service-test-model",
                request={},
                response={
                    "tool_calls": [{"name": "search", "status": "success"}],
                    "tool_metrics": {"count": 1, "total_duration_ms": 0},
                },
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                elapsed_ms=elapsed_ms,
                created_at=now - timedelta(minutes=minutes_ago),
            )

        def suite(suite_id: uuid.UUID, name: str) -> AgentSuite:
            return AgentSuite(
                id=suite_id,
                owner_id=self.owner_id,
                name=name,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                node_label="Support",
                tool_assertions=[],
                thresholds={},
                baseline={},
            )

        def suite_run(run_id: uuid.UUID, suite_id: uuid.UUID, status: str, traces: list) -> AgentSuiteRun:
            return AgentSuiteRun(
                id=run_id,
                suite_id=suite_id,
                status=status,
                requested_count=max(1, len(traces)),
                generate_inputs=False,
                inputs=[],
                results=[
                    {"execution_id": None, "status": "success", "trace_ids": [str(t)], "error": None}
                    for t in traces
                ],
            )

        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"agent_suite_service_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name="User",
                    )
                    for user_id in (self.owner_id, self.outsider_id)
                ]
            )
            await session.flush()
            session.add(
                Workflow(
                    id=self.workflow_id,
                    name="Support flow",
                    owner_id=self.owner_id,
                    nodes=[{"id": AGENT_NODE, "type": "agent", "data": {"label": "Support"}}],
                    edges=[],
                )
            )
            await session.flush()
            session.add_all([suite(self.suite_id, "Support checks"), suite(self.other_suite_id, "Other")])
            await session.flush()
            session.add_all(
                [
                    suite_run(self.finished_run_id, self.suite_id, "completed", self.suite_run_traces),
                    suite_run(self.running_run_id, self.suite_id, "running", []),
                    suite_run(self.empty_run_id, self.suite_id, "completed", []),
                    suite_run(self.other_suite_run_id, self.other_suite_id, "completed", self.suite_run_traces),
                    trace(self.suite_run_traces[0], 3, 3000.0),
                    trace(self.suite_run_traces[1], 2, 3000.0),
                    trace(uuid.uuid4(), 1, 1000.0),
                    trace(uuid.uuid4(), 1, 1000.0),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(
                delete(User).where(User.id.in_([self.owner_id, self.outsider_id]))
            )
            await session.commit()
        await engine.dispose()

    async def test_latest_runs_baseline_is_the_default(self) -> None:
        async with async_session_maker() as db:
            response = await agent_suites.create_agent_suite(
                db,
                self.owner_id,
                AgentSuiteCreate(name="New", workflow_id=self.workflow_id, node_id=AGENT_NODE),
            )
        self.assertEqual(response.baseline.source, "latest_runs")
        self.assertIsNone(response.baseline.suite_run_id)
        self.assertEqual(response.baseline.run_count, 4)

    async def test_a_finished_suite_run_becomes_the_baseline(self) -> None:
        source = AgentBaselineSource(source="suite_run", run_id=self.finished_run_id)
        async with async_session_maker() as db:
            response = await agent_suites.update_agent_suite(
                db, self.owner_id, self.suite_id, AgentSuiteUpdate(baseline=source)
            )
        self.assertEqual(response.baseline.source, "suite_run")
        self.assertEqual(response.baseline.suite_run_id, self.finished_run_id)
        self.assertEqual(response.baseline.run_count, 2)
        self.assertEqual(response.baseline.latency_p95_ms, 3000)

    async def test_a_run_that_cannot_be_a_baseline_changes_nothing(self) -> None:
        refusals = {
            self.running_run_id: ValueError,
            self.empty_run_id: ValueError,
            self.other_suite_run_id: EvalNotFoundError,
            uuid.uuid4(): EvalNotFoundError,
        }
        for run_id, error in refusals.items():
            with self.subTest(run_id=run_id):
                async with async_session_maker() as db:
                    with self.assertRaises(error):
                        await agent_suites.update_agent_suite(
                            db,
                            self.owner_id,
                            self.suite_id,
                            AgentSuiteUpdate(
                                name="changed",
                                baseline=AgentBaselineSource(source="suite_run", run_id=run_id),
                            ),
                        )
        async with async_session_maker() as db:
            suite = await agent_suites.get_agent_suite(db, self.owner_id, self.suite_id)
        self.assertEqual(suite.name, "Support checks")

    async def test_manual_values_are_stored_as_given(self) -> None:
        values = AgentBaselineValues(latency_p95_ms=2500, cost_avg_usd=0.01)
        async with async_session_maker() as db:
            response = await agent_suites.update_agent_suite(
                db,
                self.owner_id,
                self.suite_id,
                AgentSuiteUpdate(baseline=AgentBaselineSource(source="manual", values=values)),
            )
            report = await agent_suites.agent_suite_report(db, self.owner_id, self.suite_id, 10, None)
        baseline = response.baseline
        self.assertEqual(
            (baseline.source, baseline.latency_p95_ms, baseline.cost_avg_usd, baseline.run_count),
            ("manual", 2500, 0.01, 0),
        )
        deltas = {delta.metric: delta.baseline for delta in report.deltas}
        self.assertEqual(deltas["latency_p95_ms"], 2500)

    async def test_an_old_baseline_reads_as_latest_runs(self) -> None:
        async with async_session_maker() as db:
            suite = await agent_suites.get_agent_suite(db, self.owner_id, self.suite_id)
        self.assertEqual(suite.baseline.source, "latest_runs")
        self.assertIsNone(suite.baseline.suite_run_id)

    async def test_run_inputs_and_latest_run(self) -> None:
        async with async_session_maker() as db:
            inputs = await agent_suites.agent_run_inputs(db, self.owner_id, self.suite_id)
            latest = await agent_suites.latest_agent_suite_run(db, self.suite_id)
        self.assertEqual(inputs.fields, [])
        self.assertIsNone(inputs.previous_inputs)
        self.assertIn(latest.id, {self.finished_run_id, self.running_run_id, self.empty_run_id})

    async def test_another_user_reaches_nothing(self) -> None:
        async with async_session_maker() as db:
            for call in (
                agent_suites.get_agent_suite(db, self.outsider_id, self.suite_id),
                agent_suites.update_agent_suite(
                    db, self.outsider_id, self.suite_id, AgentSuiteUpdate(name="x")
                ),
                agent_suites.agent_suite_report(db, self.outsider_id, self.suite_id, 10, None),
                agent_suites.agent_run_inputs(db, self.outsider_id, self.suite_id),
                agent_suites.load_owned_agent_suite_run(db, self.finished_run_id, self.outsider_id),
                agent_suites.agent_metrics(db, self.outsider_id, self.workflow_id, AGENT_NODE, 10),
            ):
                with self.assertRaises(EvalNotFoundError):
                    await call


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_suite_service.py -v`
Expected: collection error, `ImportError: cannot import name 'AgentBaselineSource'`

- [ ] **Step 3: Extend `backend/app/models/agent_suite_schemas.py`**

Below `ToolKind = ...` (line 8), add:

```python
BaselineSource = Literal["latest_runs", "suite_run", "manual"]
```

Add these two lines at the end of the `AgentBaselineResponse` fields, after `captured_at`:

```python
    source: BaselineSource = "latest_runs"
    suite_run_id: uuid.UUID | None = None
```

Insert before `class AgentSuiteCreate`:

```python
class AgentBaselineValues(BaseModel):
    """Baseline numbers the user states instead of measuring them from runs."""

    latency_p50_ms: float | None = Field(None, gt=0)
    latency_p95_ms: float | None = Field(None, gt=0)
    cost_avg_usd: float | None = Field(None, ge=0)
    cost_p95_usd: float | None = Field(None, ge=0)
    tokens_avg: float | None = Field(None, gt=0)
    tokens_p95: float | None = Field(None, gt=0)
    tool_calls_avg: float | None = Field(None, ge=0)
    tool_calls_max: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _at_least_one_value(self) -> "AgentBaselineValues":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Give at least one baseline value")
        return self


class AgentBaselineSource(BaseModel):
    """Where a suite's baseline comes from: the agent's latest runs, one suite run, or numbers."""

    source: BaselineSource = "latest_runs"
    run_id: uuid.UUID | None = None
    values: AgentBaselineValues | None = None

    @model_validator(mode="after")
    def _source_needs_its_input(self) -> "AgentBaselineSource":
        if self.source == "suite_run" and self.run_id is None:
            raise ValueError("A suite_run baseline needs run_id")
        if self.source == "manual" and self.values is None:
            raise ValueError("A manual baseline needs values")
        return self
```

Replace `AgentSuiteCreate` and `AgentSuiteUpdate` with:

```python
class AgentSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    workflow_id: uuid.UUID
    node_id: str = Field(min_length=1, max_length=64)
    tool_assertions: list[ToolAssertion] = Field(default_factory=list, max_length=100)
    thresholds: AgentThresholdsModel = Field(default_factory=AgentThresholdsModel)
    baseline: AgentBaselineSource = Field(default_factory=AgentBaselineSource)

    @model_validator(mode="after")
    def _a_new_suite_has_no_runs(self) -> "AgentSuiteCreate":
        if self.baseline.source == "suite_run":
            raise ValueError(
                "A new suite has no runs yet. Create it, run it, then use that run as its baseline."
            )
        return self


class AgentSuiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    tool_assertions: list[ToolAssertion] | None = Field(None, max_length=100)
    thresholds: AgentThresholdsModel | None = None
    # Re-reads the agent's latest runs into the stored baseline.
    refresh_baseline: bool = False
    baseline: AgentBaselineSource | None = None

    @model_validator(mode="after")
    def _one_baseline_change(self) -> "AgentSuiteUpdate":
        if self.refresh_baseline and self.baseline is not None:
            raise ValueError("Send refresh_baseline or baseline, not both")
        return self
```

In `AgentSuiteRunCreate`, add the field after `model` and a second validator after `_generation_needs_a_model`:

```python
    # One input per run, in order; the run count is its length.
    inputs_list: list[dict[str, Any]] | None = Field(None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _inputs_list_is_not_generated(self) -> "AgentSuiteRunCreate":
        if self.inputs_list is not None and self.generate_inputs:
            raise ValueError("Send inputs_list or generate_inputs, not both")
        return self
```

- [ ] **Step 4: Create `backend/app/services/agent_suite_service.py`**

```python
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
            raise ValueError("That run is still going. Use it as the baseline once it has finished.")
        trace_ids = suite_run_trace_ids(suite_run)
        if not trace_ids:
            raise ValueError("That run recorded no runs of this agent, so it has nothing to measure.")
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
```

- [ ] **Step 5: Replace `backend/app/api/agent_suites.py`**

```python
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
```

`accessible_workflow` is gone. Task 4 updates its one importer, `agent_suite_runs.py`, so the app does not import until Task 4 lands.

- [ ] **Step 6: Run the service tests (the route tests follow in Task 4)**

Run: `uv run pytest tests/test_agent_suite_service.py -v`
Expected: 11 passed. The test does not import the routers.

`app/api/agent_suite_runs.py` still imports the removed `accessible_workflow`, so the app and `test_agent_suite_runs.py` do not import until Task 4 replaces that file. Do not commit here; Task 4 commits both tasks together.

---

### Task 4: Agent suite run launch with an input per run

**Files:**
- Modify: `backend/app/api/agent_suite_runs.py` (whole file)
- Test: `backend/tests/test_agent_suite_runs.py` (add two tests)

- [ ] **Step 1: Add the failing tests**

In `backend/tests/test_agent_suite_runs.py`, add this method to `RealPostgresAgentSuiteRunTests`, after `test_a_run_scores_only_the_traces_it_started`:

```python
    async def test_an_inputs_list_runs_each_input_once(self) -> None:
        run_id = await self._start(
            AgentSuiteRunCreate(inputs_list=[{"text": "one"}, {"text": "two"}])
        )
        executor = AsyncMock(side_effect=[self._execution_result(t) for t in self.run_trace_ids])
        with patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor):
            await execute_agent_suite_run(run_id, self.owner_id, "http://test", None, None)
        self.assertEqual(
            [call.args[3] for call in executor.await_args_list], [{"text": "one"}, {"text": "two"}]
        )
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
        self.assertEqual((suite_run.requested_count, suite_run.status), (2, "completed"))

    async def test_the_route_queues_the_launch_job(self) -> None:
        queued: list[tuple] = []
        tasks = SimpleNamespace(add_task=lambda func, **kwargs: queued.append((func, kwargs)))
        request = SimpleNamespace(headers={}, base_url="http://test/")
        async with async_session_maker() as session:
            with patch(
                "app.api.agent_suite_runs.build_public_base_url", return_value="http://test"
            ):
                started = await start_agent_suite_run(
                    self.suite_id, AgentSuiteRunCreate(count=1), request, tasks, self.owner, session
                )
        self.assertIs(queued[0][0], execute_agent_suite_run)
        self.assertEqual(queued[0][1]["run_id"], started.id)
        self.assertEqual(queued[0][1]["public_base_url"], "http://test")
```

- [ ] **Step 2: Replace `backend/app/api/agent_suite_runs.py`**

```python
"""Run an agent suite: execute its workflow a chosen number of times, then score those runs."""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_suites import owned_agent_suite
from app.api.ai_assistant import run_execute_workflow_tool
from app.api.deps import get_current_user
from app.db.models import AgentSuite, AgentSuiteRun, User
from app.db.session import get_db
from app.models.agent_suite_schemas import (
    AgentSuiteRunCreate,
    AgentSuiteRunInputsResponse,
    AgentSuiteRunResponse,
)
from app.services import agent_suite_service as agent_suites
from app.services.agent_suite_inputs import (
    agent_trace_ids,
    generate_run_inputs,
    previous_run_inputs,
)
from app.services.eval_common import DeferredJob, EvalNotFoundError
from app.services.hitl_service import build_public_base_url
from app.services.workflow_access import get_accessible_workflow

logger = logging.getLogger(__name__)

router = APIRouter()

TRIGGER_SOURCE = "agent_suite"


class AgentSuiteBusyError(Exception):
    """The suite has a run going; a second one waits until it finishes."""


@dataclass(frozen=True)
class AgentSuiteRunLaunch:
    """A created suite run row and the job that executes it."""

    suite_run: AgentSuiteRun
    job: DeferredJob


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
                    fields=agent_suites.input_keys(workflow),
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


async def launch_agent_suite_run(
    db: AsyncSession,
    user_id: uuid.UUID,
    suite: AgentSuite,
    body: AgentSuiteRunCreate,
    public_base_url: str,
) -> AgentSuiteRunLaunch:
    """Create the run row ``body`` asks for and the job that runs it.

    ``suite`` is one the user owns. Raises ``AgentSuiteBusyError`` while another run of it is
    going, and ``EvalNotFoundError`` when its workflow is out of reach.
    """
    await agent_suites.load_accessible_workflow(db, suite.workflow_id, user_id)
    running = await db.execute(
        select(AgentSuiteRun.id).where(
            AgentSuiteRun.suite_id == suite.id, AgentSuiteRun.status == "running"
        )
    )
    if running.first() is not None:
        raise AgentSuiteBusyError("This suite is already running")
    if body.inputs_list is not None:
        inputs = [dict(item) for item in body.inputs_list]
        requested = len(inputs)
    elif body.generate_inputs:
        # The edited form is the example the model varies.
        inputs = [body.inputs] if body.inputs else []
        requested = body.count
    else:
        inputs = [body.inputs] * body.count
        requested = body.count
    suite_run = AgentSuiteRun(
        suite_id=suite.id,
        status="running",
        requested_count=requested,
        generate_inputs=body.generate_inputs,
        inputs=inputs,
        results=[],
    )
    db.add(suite_run)
    await db.commit()
    await db.refresh(suite_run)
    job = DeferredJob(
        execute_agent_suite_run,
        {
            "run_id": suite_run.id,
            "user_id": user_id,
            "public_base_url": public_base_url,
            "credential_id": body.credential_id,
            "model": (body.model or "").strip() or None,
        },
    )
    return AgentSuiteRunLaunch(suite_run=suite_run, job=job)


@router.get("/agent-suites/{suite_id}/run-inputs", response_model=AgentSuiteRunInputsResponse)
async def get_run_inputs(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunInputsResponse:
    """The workflow's input fields, filled with the values of its most recent run."""
    try:
        return await agent_suites.agent_run_inputs(db, current_user.id, suite_id)
    except EvalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
    """Run the workflow in the background, with the given inputs, one input per run, or
    inputs a model writes, and score the agent's runs once they finish."""
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    try:
        launch = await launch_agent_suite_run(
            db, current_user.id, suite, body, build_public_base_url(request)
        )
    except EvalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentSuiteBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    background_tasks.add_task(launch.job.func, **launch.job.kwargs)
    return AgentSuiteRunResponse.model_validate(launch.suite_run)


@router.get("/agent-suites/{suite_id}/runs/latest", response_model=AgentSuiteRunResponse | None)
async def get_latest_agent_suite_run(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunResponse | None:
    suite = await owned_agent_suite(db, suite_id, current_user.id)
    suite_run = await agent_suites.latest_agent_suite_run(db, suite.id)
    return AgentSuiteRunResponse.model_validate(suite_run) if suite_run else None


@router.get("/agent-suite-runs/{run_id}", response_model=AgentSuiteRunResponse)
async def get_agent_suite_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSuiteRunResponse:
    try:
        suite_run = await agent_suites.load_owned_agent_suite_run(db, run_id, current_user.id)
    except EvalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AgentSuiteRunResponse.model_validate(suite_run)
```

- [ ] **Step 3: Run every agent suite test and lint**

Run: `uv run pytest tests/test_agent_suite_service.py tests/test_agent_suites_api.py tests/test_agent_suite_runs.py tests/test_agent_suite_metrics.py -v && uv run ruff check app/api/agent_suites.py app/api/agent_suite_runs.py app/services/agent_suite_service.py app/models/agent_suite_schemas.py`
Expected: all pass, including the 11 new service tests and the 2 new run tests, and `All checks passed!`

- [ ] **Step 4: Commit Tasks 3 and 4 together**

```bash
git add backend/app/models/agent_suite_schemas.py backend/app/services/agent_suite_service.py \
  backend/app/api/agent_suites.py backend/app/api/agent_suite_runs.py \
  backend/tests/test_agent_suite_service.py backend/tests/test_agent_suite_runs.py
git commit -m "feat(evals): agent suite service with baseline sources and an input per run"
```

---

### Task 5: Credential model listing as one function

**Files:**
- Modify: `backend/app/api/credentials.py:1917-1977` (`get_credential_models`)
- Test: `backend/tests/test_credential_models_listing.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_credential_models_listing.py`:

```python
"""list_credential_models: the model list the credential route and the chat tools share."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.credentials import build_model_router_models, list_credential_models
from app.db.models import CredentialType
from app.models.schemas import LLMModel


class CredentialModelsListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_type_without_models_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            await list_credential_models(
                SimpleNamespace(type=CredentialType.slack, encrypted_config="x")
            )

    async def test_a_model_router_lists_its_pseudo_model(self) -> None:
        models = await list_credential_models(
            SimpleNamespace(type=CredentialType.model_router, encrypted_config="x")
        )
        self.assertEqual(models, build_model_router_models())

    async def test_known_context_windows_are_filled_in(self) -> None:
        fetched = [LLMModel(id="gpt-4o-2024-08-06", name="gpt-4o")]
        with (
            patch("app.api.credentials.decrypt_config", return_value={"api_key": "k"}),
            patch("app.services.llm_provider.fetch_models", AsyncMock(return_value=fetched)),
        ):
            models = await list_credential_models(
                SimpleNamespace(type=CredentialType.openai, encrypted_config="x")
            )
        self.assertEqual(models[0].context_window, 128_000)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_credential_models_listing.py -v`
Expected: `ImportError: cannot import name 'list_credential_models'`

- [ ] **Step 3: Extract the function and make the route call it**

In `backend/app/api/credentials.py`, insert this function directly above `@router.get("/{credential_id}/models", ...)`:

```python
async def list_credential_models(credential: Credential) -> list[LLMModel]:
    """The models an LLM credential offers. Raises ValueError for a type that lists none,
    and for an endpoint the SSRF guard blocks."""
    if credential.type == CredentialType.model_router:
        return build_model_router_models()
    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise ValueError("This credential type does not support model listing")

    config = decrypt_config(credential.encrypted_config)

    from app.services.context_compressor import KNOWN_LIMITS
    from app.services.llm_provider import fetch_models

    models = await fetch_models(credential.type, config)
    for m in models:
        model_lower = m.id.lower()
        for key, limit in KNOWN_LIMITS.items():
            if key in model_lower:
                m.context_window = limit
                break
    return models
```

In `get_credential_models`, keep the three access lookups and the 404. Replace everything after the `if credential is None: raise HTTPException(... 404 ...)` block with:

```python
    try:
        return await list_credential_models(credential)
    except ValueError as exc:
        # SsrfBlockedError is a ValueError: both are a 400 for the caller.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

If `SsrfBlockedError` is no longer referenced anywhere in `credentials.py`, remove its import. Run `uv run ruff check app/api/credentials.py` to find out.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_credential_models_listing.py -v && uv run pytest tests -q -k "credential and model" && uv run ruff check app/api/credentials.py`
Expected: 3 passed, the existing credential model tests pass, and `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/credentials.py backend/tests/test_credential_models_listing.py
git commit -m "refactor(credentials): one model listing for the route and chat"
```

---

### Task 6: Shared tool outcome and the eval mode rules

**Files:**
- Modify: `backend/app/services/chat_build_mode.py`
- Modify: `backend/app/api/chat_build.py:1-240`
- Create: `backend/app/services/chat_eval_mode.py`
- Test: `backend/tests/test_chat_eval_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chat_eval_mode.py`:

```python
"""Eval tools in chat: argument parsing, result shapes and the prompt section."""

import unittest
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from app.models.agent_suite_schemas import (
    AgentBaselineResponse,
    AgentBaselineSource,
    AgentCheckResultResponse,
    AgentCheckSummaryResponse,
    AgentMetricDeltaResponse,
    AgentRunEvaluationResponse,
    AgentSuiteReportResponse,
    AgentSuiteRunResponse,
    AgentSuiteRunResult,
)
from app.models.eval_schemas import EvalRunResponse, EvalRunResultResponse
from app.services import chat_eval_mode as mode
from app.services.agent_suite_inputs import MAX_SUITE_RUNS

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _result(model: str, score: str, actual: str, **extra: object) -> EvalRunResultResponse:
    return EvalRunResultResponse(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        test_case_id=None,
        model_id=model,
        input_snapshot="question",
        expected_output_snapshot="answer",
        actual_output=actual,
        score=score,
        latency_ms=extra.get("latency_ms"),
        tokens_used=extra.get("tokens_used"),
        error=extra.get("error"),
        explanation=extra.get("explanation"),
        created_at=NOW,
    )


def _run(results: list[EvalRunResultResponse], status: str = "completed") -> EvalRunResponse:
    return EvalRunResponse(
        id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
        name="Run #1",
        system_prompt_snapshot="",
        models=["gpt-4o", "gpt-4.1-mini"],
        scoring_method="exact_match",
        temperature=0.7,
        max_tokens=None,
        status=status,
        created_at=NOW,
        completed_at=NOW,
        results=results,
    )


class ArgumentTests(unittest.TestCase):
    def test_ids_are_parsed_or_refused(self) -> None:
        value = uuid.uuid4()
        self.assertEqual(mode.uuid_arg({"suite_id": str(value)}, "suite_id"), value)
        self.assertIsNone(mode.optional_uuid_arg({}, "suite_id"))
        with self.assertRaises(ValueError):
            mode.uuid_arg({}, "suite_id")
        with self.assertRaises(ValueError):
            mode.uuid_arg({"suite_id": "nope"}, "suite_id")

    def test_lists_and_numbers(self) -> None:
        self.assertEqual(mode.list_arg({}, "inputs"), [])
        with self.assertRaises(ValueError):
            mode.list_arg({"inputs": "x"}, "inputs")
        self.assertEqual(mode.number_arg({"w": 500}, "w", default=30, low=0, high=120), 120)
        self.assertEqual(mode.number_arg({}, "w", default=30, low=0, high=120), 30)

    def test_validation_errors_read_short(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            AgentBaselineSource(source="manual")
        self.assertEqual(mode.error_text(ctx.exception), "A manual baseline needs values")
        self.assertEqual(mode.error_text(ValueError("plain")), "plain")

    def test_suite_url_is_absolute(self) -> None:
        self.assertEqual(
            mode.suite_url("https://heym.example/", "abc"), "https://heym.example/evals?suite=abc"
        )


class SummaryTests(unittest.TestCase):
    def test_prompt_run_counts_per_model_and_keeps_five_failures(self) -> None:
        results = [
            _result("gpt-4o", "pass", "answer", latency_ms=100, tokens_used=10),
            _result("gpt-4o", "fail", "x" * 1000, latency_ms=300, tokens_used=30),
            *[_result("gpt-4.1-mini", "0", "wrong", explanation="off") for _ in range(6)],
        ]
        summary = mode.summarize_prompt_run(_run(results))
        self.assertEqual(
            summary["models"],
            [
                {"model": "gpt-4o", "passed": 1, "total": 2, "avg_latency_ms": 200, "avg_tokens": 20},
                {"model": "gpt-4.1-mini", "passed": 0, "total": 6},
            ],
        )
        self.assertEqual(summary["failed_count"], 7)
        self.assertEqual(len(summary["failures"]), mode.MAX_FAILURES_SHOWN)
        self.assertLessEqual(len(summary["failures"][0]["actual"]), mode.TEXT_MAX_CHARS)

    def test_agent_run_keeps_failed_runs_and_their_failed_checks(self) -> None:
        def evaluation(passed: bool) -> AgentRunEvaluationResponse:
            status = "pass" if passed else "fail"
            return AgentRunEvaluationResponse(
                trace_id=uuid.uuid4(),
                created_at=NOW,
                model="m",
                latency_ms=1.0,
                model_ms=1.0,
                tool_ms=0.0,
                cost_usd=None,
                total_tokens=1,
                tool_count=0,
                tool_calls=[],
                error=None,
                passed=passed,
                checks=[
                    AgentCheckResultResponse(
                        key="tool:tool:search", label="search", kind="assertion", status=status
                    )
                ],
            )

        report = AgentSuiteReportResponse(
            suite_id=uuid.uuid4(),
            run_count=2,
            passed_count=1,
            pass_rate=50.0,
            checks=[
                AgentCheckSummaryResponse(
                    key="tool:tool:search", label="search", kind="assertion", passed=1, failed=1, skipped=0
                )
            ],
            current=AgentBaselineResponse(),
            baseline=AgentBaselineResponse(),
            deltas=[
                AgentMetricDeltaResponse(metric="latency_p95_ms", baseline=None, current=1.0, delta_pct=None)
            ],
            runs=[evaluation(True), evaluation(False)],
        )
        suite_run = AgentSuiteRunResponse(
            id=uuid.uuid4(),
            suite_id=report.suite_id,
            status="completed",
            requested_count=2,
            generate_inputs=False,
            inputs=[{}, {}],
            results=[AgentSuiteRunResult(status="success"), AgentSuiteRunResult(status="error")],
            error=None,
            created_at=NOW,
            completed_at=NOW,
        )
        summary = mode.summarize_agent_run(suite_run, report)
        self.assertEqual(summary["execution_statuses"], {"success": 1, "error": 1})
        self.assertEqual(summary["report"]["pass_rate"], 50.0)
        self.assertEqual(
            summary["report"]["failed_runs"][0]["failed_checks"], [{"label": "search"}]
        )
        self.assertEqual(
            summary["report"]["deltas"], [{"metric": "latency_p95_ms", "current": 1.0}]
        )

    def test_step_summaries(self) -> None:
        self.assertEqual(mode.step_summary(mode.LIST_EVAL_SUITES_TOOL, {"count": 2}), "2 suites")
        running = {"status": "running", "suite_type": "prompt"}
        self.assertEqual(mode.step_summary(mode.RUN_EVAL_SUITE_TOOL, running), "Still running")
        done = {
            "status": "completed",
            "suite_type": "prompt",
            "models": [{"model": "gpt-4o", "passed": 4, "total": 5}],
        }
        self.assertEqual(mode.step_summary(mode.GET_EVAL_RUN_TOOL, done), "gpt-4o: 4/5 passed")


class InstructionTests(unittest.TestCase):
    def test_the_prompt_section_states_the_rules(self) -> None:
        text = mode.eval_instructions()
        self.assertIn("## Eval suites", text)
        self.assertIn("When exactly one fits, use it without asking", text)
        self.assertIn('"source": "suite_run"', text)
        self.assertIn('"source": "manual"', text)
        self.assertIn(f"At most {MAX_SUITE_RUNS} per call", text)

    def test_every_tool_has_a_step_label(self) -> None:
        self.assertEqual(len(mode.EVAL_TOOL_NAMES), 9)
        for name in mode.EVAL_TOOL_NAMES:
            self.assertTrue(mode.STEP_LABELS[name].endswith("..."))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_chat_eval_mode.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.chat_eval_mode'`

- [ ] **Step 3: Move `BuildToolOutcome` into `chat_build_mode.py` and make truncation public**

In `backend/app/services/chat_build_mode.py`:

1. Rename `_truncate` to `truncate_text`: its definition (line 88) and its three call sites (lines 103, 125, 142).
2. Add this after the `BuildProgress` class:

```python
@dataclass(frozen=True)
class BuildToolOutcome:
    """One tool call of a build turn: the result for the model, the step row and extra
    stream events."""

    result: str
    summary: str
    status: str
    events: list[dict[str, Any]] = field(default_factory=list)
    finished_summary: str | None = None


def tool_error(message: str) -> BuildToolOutcome:
    return BuildToolOutcome(
        result=json.dumps({"status": "error", "error": message}),
        summary=f"Error: {message}",
        status="error",
    )
```

In `backend/app/api/chat_build.py`:

1. Delete the `BuildToolOutcome` class and the `_error` function (lines 223-239).
2. Delete the `from dataclasses import dataclass, field` line.
3. Add `BuildToolOutcome` and `tool_error` to the existing `from app.services.chat_build_mode import (...)` block.
4. Rename the remaining call sites:

```bash
perl -pi -e 's/(?<![\w.])_error\(/tool_error(/g' backend/app/api/chat_build.py
```

- [ ] **Step 4: Create `backend/app/services/chat_eval_mode.py`**

```python
"""Eval tools in chat: names, limits, argument parsing, result shapes and the prompt section,
without database or model access.

`app/api/chat_evals.py` runs the tools. Build turns of the dashboard chat (Chat tab, MCP
`heym_chat`, Heym Work Chat) offer them; skill-only turns and the canvas assistant do not,
and MCP clients never see them in `tools/list`.
"""

import uuid
from collections import Counter
from statistics import mean
from typing import Any

from pydantic import ValidationError

from app.models.agent_suite_schemas import (
    AgentBaselineResponse,
    AgentSuiteReportResponse,
    AgentSuiteRunResponse,
)
from app.models.eval_schemas import EvalRunResponse, EvalRunResultResponse
from app.services.agent_suite_inputs import MAX_SUITE_RUNS
from app.services.chat_build_mode import truncate_text
from app.services.prompt_suite_service import is_passing

LIST_EVAL_SUITES_TOOL = "list_eval_suites"
GET_EVAL_SUITE_TOOL = "get_eval_suite"
LIST_EVAL_AGENTS_TOOL = "list_eval_agents"
GET_AGENT_BASELINE_TOOL = "get_agent_baseline"
LIST_LLM_MODELS_TOOL = "list_llm_models"
SAVE_PROMPT_SUITE_TOOL = "save_prompt_suite"
SAVE_AGENT_SUITE_TOOL = "save_agent_suite"
RUN_EVAL_SUITE_TOOL = "run_eval_suite"
GET_EVAL_RUN_TOOL = "get_eval_run"

STEP_LABELS: dict[str, str] = {
    LIST_EVAL_SUITES_TOOL: "Listing eval suites...",
    GET_EVAL_SUITE_TOOL: "Reading the eval suite...",
    LIST_EVAL_AGENTS_TOOL: "Listing agents...",
    GET_AGENT_BASELINE_TOOL: "Reading the agent's baseline...",
    LIST_LLM_MODELS_TOOL: "Listing models...",
    SAVE_PROMPT_SUITE_TOOL: "Saving the prompt suite...",
    SAVE_AGENT_SUITE_TOOL: "Saving the agent suite...",
    RUN_EVAL_SUITE_TOOL: "Running the eval suite...",
    GET_EVAL_RUN_TOOL: "Checking the eval run...",
}
EVAL_TOOL_NAMES = frozenset(STEP_LABELS)

RUN_WAIT_SECONDS = 60.0
GET_RUN_DEFAULT_WAIT_SECONDS = 30.0
GET_RUN_MAX_WAIT_SECONDS = 120.0
RUN_POLL_SECONDS = 2.0
MAX_FAILURES_SHOWN = 5
MAX_TEST_CASES_SHOWN = 50
MAX_MODELS_SHOWN = 100
TEXT_MAX_CHARS = 400


def parse_uuid(raw: object, key: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise ValueError(f"{key} must be an id") from None


def uuid_arg(args: dict[str, Any], key: str) -> uuid.UUID:
    raw = args.get(key)
    if raw is None or raw == "":
        raise ValueError(f"{key} is required")
    return parse_uuid(raw, key)


def optional_uuid_arg(args: dict[str, Any], key: str) -> uuid.UUID | None:
    raw = args.get(key)
    if raw is None or raw == "":
        return None
    return parse_uuid(raw, key)


def list_arg(args: dict[str, Any], key: str) -> list[Any]:
    value = args.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def number_arg(
    args: dict[str, Any], key: str, *, default: float, low: float, high: float
) -> float:
    raw = args.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number") from None
    return max(low, min(high, value))


def error_text(exc: Exception) -> str:
    """A short message for the model: pydantic's field errors without the boilerplate."""
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            message = str(error["msg"]).removeprefix("Value error, ")
            parts.append(f"{location}: {message}" if location else message)
        return "; ".join(parts)
    return str(exc)


def suite_url(public_base_url: str, suite_id: object) -> str:
    """The suite on the Evals page, on the public origin so MCP clients can open it."""
    return f"{public_base_url.rstrip('/')}/evals?suite={suite_id}"


def without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def without_empty(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, [], {})}


def compact_baseline(baseline: AgentBaselineResponse) -> dict[str, Any]:
    return without_empty(baseline.model_dump(mode="json"))


def _short(text: str | None) -> str | None:
    return truncate_text(text, TEXT_MAX_CHARS) if text else None


def summarize_prompt_run(run: EvalRunResponse) -> dict[str, Any]:
    """Pass counts per model and the first failed cases of a finished prompt run."""
    by_model: dict[str, list[EvalRunResultResponse]] = {}
    for result in run.results:
        by_model.setdefault(result.model_id, []).append(result)
    order = [*run.models, *(model for model in by_model if model not in run.models)]
    models = []
    for model in order:
        results = by_model.get(model, [])
        latencies = [r.latency_ms for r in results if r.latency_ms is not None]
        tokens = [r.tokens_used for r in results if r.tokens_used is not None]
        models.append(
            without_empty(
                {
                    "model": model,
                    "passed": sum(1 for r in results if is_passing(r.score)),
                    "total": len(results),
                    "avg_latency_ms": round(mean(latencies)) if latencies else None,
                    "avg_tokens": round(mean(tokens)) if tokens else None,
                }
            )
        )
    failed = [r for r in run.results if not is_passing(r.score)]
    failures = [
        without_empty(
            {
                "model": r.model_id,
                "input": _short(r.input_snapshot),
                "expected": _short(r.expected_output_snapshot),
                "actual": _short(r.actual_output),
                "score": r.score,
                "explanation": _short(r.explanation),
                "error": _short(r.error),
            }
        )
        for r in failed[:MAX_FAILURES_SHOWN]
    ]
    return without_empty(
        {
            "run_id": str(run.id),
            "suite_type": "prompt",
            "name": run.name,
            "status": run.status,
            "scoring_method": run.scoring_method,
            "judge_model": run.judge_model,
            "models": models,
            "failed_count": len(failed),
            "failures": failures,
        }
    )


def summarize_agent_run(
    suite_run: AgentSuiteRunResponse, report: AgentSuiteReportResponse | None
) -> dict[str, Any]:
    """How a suite run's executions ended and, once it is over, how its agent runs scored."""
    payload: dict[str, Any] = {
        "run_id": str(suite_run.id),
        "suite_type": "agent",
        "status": suite_run.status,
        "requested_runs": suite_run.requested_count,
        "finished_runs": len(suite_run.results),
        "execution_statuses": dict(Counter(result.status for result in suite_run.results)),
    }
    if suite_run.error:
        payload["error"] = _short(suite_run.error)
    if report is None:
        return payload
    failed_runs = [run for run in report.runs if not run.passed]
    payload["report"] = {
        "run_count": report.run_count,
        "passed_count": report.passed_count,
        "pass_rate": report.pass_rate,
        "checks": [
            {"label": c.label, "passed": c.passed, "failed": c.failed, "skipped": c.skipped}
            for c in report.checks
        ],
        "deltas": [
            without_empty(
                {
                    "metric": d.metric,
                    "baseline": d.baseline,
                    "current": d.current,
                    "delta_pct": d.delta_pct,
                }
            )
            for d in report.deltas
        ],
        "failed_runs": [
            {
                "trace_id": str(run.trace_id),
                "failed_checks": [
                    without_empty({"label": c.label, "detail": c.detail})
                    for c in run.checks
                    if c.status == "fail"
                ],
            }
            for run in failed_runs[:MAX_FAILURES_SHOWN]
        ],
    }
    return payload


def step_summary(name: str, payload: dict[str, Any]) -> str:
    """The one-line step row the chat shows for a finished tool call."""
    if name == LIST_EVAL_SUITES_TOOL:
        return f"{payload['count']} suites"
    if name == LIST_EVAL_AGENTS_TOOL:
        return f"{payload['count']} agents"
    if name == LIST_LLM_MODELS_TOOL:
        return f"{len(payload['models'])} models"
    if name == GET_AGENT_BASELINE_TOOL:
        return f"Baseline from {payload['run_count']} runs"
    if name in (GET_EVAL_SUITE_TOOL, SAVE_PROMPT_SUITE_TOOL, SAVE_AGENT_SUITE_TOOL):
        suite = payload["suite"]
        verb = "Read" if name == GET_EVAL_SUITE_TOOL else "Saved"
        return f'{verb} {suite["suite_type"]} suite "{suite["name"]}"'
    if payload.get("status") == "running":
        return "Still running"
    if payload.get("suite_type") == "prompt":
        counts = [
            f"{m['model']}: {m.get('passed', 0)}/{m.get('total', 0)} passed"
            for m in payload.get("models", [])
        ]
        return ", ".join(counts) or str(payload.get("status"))
    report = payload.get("report") or {}
    return f"{report.get('passed_count', 0)}/{report.get('run_count', 0)} runs passed"


def eval_instructions() -> str:
    """The eval section of the build-mode system prompt."""
    lines = [
        "",
        "## Eval suites",
        "",
        "You can create, change and run the user's eval suites in Evals. A prompt suite scores "
        "a system prompt's answers to test cases on one or more models. An agent suite checks "
        "one agent node's runs against tool-call assertions and thresholds and compares them "
        "with a baseline.",
        "",
        "Prompt suites:",
        "- Before you create a prompt suite, or run one when this conversation has not settled "
        "it, settle the run settings. The LLM credential: the user's credentials of type "
        "openai, google, custom or model_router in the Credentials list. When exactly one "
        "fits, use it without asking and name it in your reply. Otherwise ask with one "
        "heym-clarify single question listing them, following the Credentials rules. The "
        "models: call list_llm_models for that credential and ask which to compare, unless "
        "the user named them. For llm_judge scoring, also ask whether a separate judge "
        "credential and model should score the answers, or each model scores its own.",
        "- Write the test cases yourself, each with an input and its expected output, from the "
        "system prompt and the user's goal: 5 unless the user asks for another number. Choose "
        "the scoring method that fits: exact_match for fixed labels, contains for key facts, "
        "llm_judge for free text.",
        "- To change a suite, read it with get_eval_suite, then pass case ids to change cases, "
        "delete_test_case_ids to remove them, and new cases without an id.",
        "",
        "Agent suites:",
        "- Find the agent with list_eval_agents. When several match the user's words, ask which.",
        "- Runs execute the real workflow, so its side effects happen. Run an agent suite only "
        "when the user asked for runs or for a baseline built from runs, and say how many runs "
        f"you start. At most {MAX_SUITE_RUNS} per call.",
        "- Write the run inputs yourself: one object per run, keyed by input_fields from "
        "get_eval_suite, shaped like previous_inputs when there is one, realistic and varied.",
        "- Report the baseline with get_agent_baseline, or the stored baseline from "
        "get_eval_suite. When the agent has no runs, or the user wants a baseline from fresh "
        "runs, run the suite, wait until the run has completed, then call save_agent_suite "
        'with baseline {"source": "suite_run", "run_id": "<run id>"} and offer the suggested '
        "thresholds it returns. When the user states numbers, save "
        '{"source": "manual", "values": {...}}.',
        "",
        "Runs and replies:",
        f"- run_eval_suite waits up to {int(RUN_WAIT_SECONDS)} seconds. When it returns status "
        "running, say the run continues in Evals, or call get_eval_run to wait longer.",
        "- Link every suite you mention with its url as a markdown link. Never ask again what "
        "this conversation already answered.",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_chat_eval_mode.py tests/test_chat_build_mode.py tests/test_chat_build_session.py tests/test_chat_build_stream.py -v && uv run ruff check app/services/chat_eval_mode.py app/services/chat_build_mode.py app/api/chat_build.py`
Expected: all pass, and `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chat_build_mode.py backend/app/api/chat_build.py \
  backend/app/services/chat_eval_mode.py backend/tests/test_chat_eval_mode.py
git commit -m "feat(chat): eval tool rules, limits and result shapes"
```

---

### Task 7: The chat eval tools

**Files:**
- Create: `backend/app/api/chat_evals.py`
- Test: `backend/tests/test_chat_evals.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chat_evals.py`:

```python
"""Eval tools in the dashboard chat, against real PostgreSQL.

Covers what a Chat tab or `heym_chat` turn can do with eval suites: create and change
prompt and agent suites, run them and wait for the result, build an agent's baseline from
a chat run, and never reach another user's suites, runs or credentials. The workflow and
model calls are stubbed; everything the tools read and write is real.
"""

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete

from app.api import chat_evals
from app.db.models import Credential, CredentialType, EvalRun, EvalRunResult, LLMTrace, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.schemas import LLMModel
from app.services import eval_service

AGENT_NODE = "agent-1"
BASE_URL = "https://heym.example"


class RealPostgresChatEvalToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.credential_id = uuid.uuid4()
        self.outsider_credential_id = uuid.uuid4()
        self.run_trace_ids = [uuid.uuid4(), uuid.uuid4()]
        now = datetime.now(timezone.utc)

        def trace(trace_id: uuid.UUID, minutes_ago: int, elapsed_ms: float) -> LLMTrace:
            return LLMTrace(
                id=trace_id,
                user_id=self.owner_id,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                source="workflow",
                request_type="chat.completions",
                model="chat-evals-test-model",
                request={},
                response={
                    "tool_calls": [{"name": "search", "status": "success"}],
                    "tool_metrics": {"count": 1, "total_duration_ms": 0},
                },
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                elapsed_ms=elapsed_ms,
                created_at=now - timedelta(minutes=minutes_ago),
            )

        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"chat_evals_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name="User",
                    )
                    for user_id in (self.owner_id, self.outsider_id)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Credential(
                        id=self.credential_id,
                        owner_id=self.owner_id,
                        name=f"openai-{self.credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                    Credential(
                        id=self.outsider_credential_id,
                        owner_id=self.outsider_id,
                        name=f"theirs-{self.outsider_credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                    Workflow(
                        id=self.workflow_id,
                        name="Support flow",
                        owner_id=self.owner_id,
                        nodes=[
                            {
                                "id": "start",
                                "type": "textInput",
                                "data": {"label": "start", "inputFields": [{"key": "text"}]},
                            },
                            {"id": AGENT_NODE, "type": "agent", "data": {"label": "Support Agent"}},
                        ],
                        edges=[{"id": "e1", "source": "start", "target": AGENT_NODE}],
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    trace(self.run_trace_ids[0], 2, 3000.0),
                    trace(self.run_trace_ids[1], 1, 3000.0),
                    trace(uuid.uuid4(), 30, 1000.0),
                ]
            )
            await session.commit()
        self.owner = SimpleNamespace(id=self.owner_id)
        self.tools = self._tools(self.owner)

    async def asyncTearDown(self) -> None:
        user_ids = [self.owner_id, self.outsider_id]
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(delete(Credential).where(Credential.owner_id.in_(user_ids)))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()

    def _tools(self, user: Any, cancel_event: Event | None = None) -> chat_evals.ChatEvalTools:
        tools = chat_evals.ChatEvalTools(
            user=user, public_base_url=BASE_URL + "/", cancel_event=cancel_event
        )
        tools.poll_seconds = 0.01
        return tools

    async def _ok(self, name: str, args: dict, tools: Any = None) -> dict:
        outcome = await (tools or self.tools).call(name, args)
        self.assertEqual(outcome.status, "success", outcome.result)
        return json.loads(outcome.result)

    async def _error(self, name: str, args: dict, tools: Any = None) -> str:
        outcome = await (tools or self.tools).call(name, args)
        self.assertEqual(outcome.status, "error", outcome.result)
        return json.loads(outcome.result)["error"]

    def _execution_result(self, trace_id: uuid.UUID) -> str:
        return json.dumps(
            {
                "status": "success",
                "execution_history_id": str(uuid.uuid4()),
                "node_results": [
                    {"node_id": AGENT_NODE, "metadata": {"trace_id": str(trace_id)}},
                ],
            }
        )

    async def _prompt_suite(self, cases: int = 2) -> dict:
        return await self._ok(
            "save_prompt_suite",
            {
                "name": "Math",
                "test_cases": [
                    {"input": f"{i}+{i}", "expected_output": str(2 * i)} for i in range(1, cases + 1)
                ],
            },
        )

    async def _agent_suite(self) -> dict:
        return await self._ok(
            "save_agent_suite",
            {
                "name": "Support checks",
                "workflow_id": str(self.workflow_id),
                "node_id": AGENT_NODE,
                "tool_assertions": [{"kind": "tool", "name": "search", "expect": "called"}],
            },
        )

    async def test_a_prompt_suite_is_created_listed_and_read(self) -> None:
        saved = await self._ok(
            "save_prompt_suite",
            {
                "name": "Support replies",
                "system_prompt": "Answer in one sentence.",
                "scoring_method": "contains",
                "test_cases": [
                    {"input": "Where is my order?", "expected_output": "tracking"},
                    {"input": "Can I return it?", "expected_output": "30 days"},
                ],
            },
        )
        suite_id = saved["suite"]["id"]
        self.assertEqual(saved["url"], f"{BASE_URL}/evals?suite={suite_id}")
        self.assertEqual(
            [case["input"] for case in saved["suite"]["test_cases"]],
            ["Where is my order?", "Can I return it?"],
        )
        listed = await self._ok("list_eval_suites", {})
        self.assertIn(
            {"id": suite_id, "name": "Support replies", "suite_type": "prompt", "url": saved["url"]},
            listed["suites"],
        )
        read = await self._ok("get_eval_suite", {"suite_id": suite_id})
        self.assertEqual(read["suite"]["scoring_method"], "contains")
        self.assertEqual(read["latest_runs"], [])

    async def test_an_edit_changes_adds_and_removes_cases_together(self) -> None:
        saved = await self._prompt_suite()
        first, second = saved["suite"]["test_cases"]
        edited = await self._ok(
            "save_prompt_suite",
            {
                "suite_id": saved["suite"]["id"],
                "name": "Math v2",
                "test_cases": [
                    {"id": first["id"], "expected_output": "two"},
                    {"input": "3+3", "expected_output": "6"},
                ],
                "delete_test_case_ids": [second["id"]],
            },
        )
        self.assertEqual(edited["suite"]["name"], "Math v2")
        self.assertEqual(
            [(c["input"], c["expected_output"]) for c in edited["suite"]["test_cases"]],
            [("1+1", "two"), ("3+3", "6")],
        )

    async def test_a_refused_edit_changes_nothing(self) -> None:
        saved = await self._prompt_suite(cases=1)
        suite_id = saved["suite"]["id"]
        error = await self._error(
            "save_prompt_suite",
            {"suite_id": suite_id, "name": "Renamed", "delete_test_case_ids": [str(uuid.uuid4())]},
        )
        self.assertIn("Not a test case of this suite", error)
        error = await self._error(
            "save_prompt_suite", {"suite_id": suite_id, "scoring_method": "regex"}
        )
        self.assertIn("Scoring method must be one of", error)
        error = await self._error(
            "save_prompt_suite",
            {"name": "New", "test_cases": [{"id": saved["suite"]["test_cases"][0]["id"]}]},
        )
        self.assertIn("A new suite has no test cases", error)
        read = await self._ok("get_eval_suite", {"suite_id": suite_id})
        self.assertEqual(read["suite"]["name"], "Math")
        self.assertEqual(len(read["suite"]["test_cases"]), 1)

    async def test_a_prompt_run_waits_for_its_result(self) -> None:
        saved = await self._prompt_suite()

        async def finish(*, run_id: uuid.UUID, **_kwargs: Any) -> None:
            async with async_session_maker() as session:
                run = await session.get(EvalRun, run_id)
                session.add_all(
                    [
                        EvalRunResult(
                            run_id=run_id,
                            model_id="gpt-4o",
                            input_snapshot="1+1",
                            expected_output_snapshot="2",
                            actual_output="2",
                            score="pass",
                            latency_ms=120,
                            tokens_used=30,
                            run_order=0,
                        ),
                        EvalRunResult(
                            run_id=run_id,
                            model_id="gpt-4o",
                            input_snapshot="2+2",
                            expected_output_snapshot="4",
                            actual_output="5",
                            score="fail",
                            latency_ms=80,
                            tokens_used=20,
                            run_order=1,
                        ),
                    ]
                )
                run.status = "completed"
                await session.commit()

        with patch.object(
            eval_service, "execute_evals_for_run", AsyncMock(side_effect=finish)
        ) as execute:
            result = await self._ok(
                "run_eval_suite",
                {
                    "suite_id": saved["suite"]["id"],
                    "credential_id": str(self.credential_id),
                    "models": ["gpt-4o"],
                },
            )
        self.assertEqual(execute.await_args.kwargs["scoring_method"], "exact_match")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["models"],
            [{"model": "gpt-4o", "passed": 1, "total": 2, "avg_latency_ms": 100, "avg_tokens": 25}],
        )
        self.assertEqual([failure["actual"] for failure in result["failures"]], ["5"])
        self.assertEqual(result["url"], f"{BASE_URL}/evals?suite={saved['suite']['id']}")
        outsider = self._tools(SimpleNamespace(id=self.outsider_id))
        error = await self._error("get_eval_run", {"run_id": result["run_id"]}, outsider)
        self.assertEqual(error, "Run not found")

    async def test_a_run_on_another_users_credential_is_refused(self) -> None:
        saved = await self._prompt_suite()
        error = await self._error(
            "run_eval_suite",
            {
                "suite_id": saved["suite"]["id"],
                "credential_id": str(self.outsider_credential_id),
                "models": ["gpt-4o"],
            },
        )
        self.assertEqual(error, "Credential not found")

    async def test_a_long_run_returns_running_and_can_be_checked_later(self) -> None:
        saved = await self._prompt_suite()
        release = asyncio.Event()

        async def slow(*, run_id: uuid.UUID, **_kwargs: Any) -> None:
            await release.wait()
            async with async_session_maker() as session:
                run = await session.get(EvalRun, run_id)
                run.status = "completed"
                await session.commit()

        self.tools.run_wait_seconds = 0.05
        args = {
            "suite_id": saved["suite"]["id"],
            "credential_id": str(self.credential_id),
            "models": ["gpt-4o"],
        }
        with patch.object(eval_service, "execute_evals_for_run", AsyncMock(side_effect=slow)):
            started = await self._ok("run_eval_suite", args)
            self.assertEqual(started["status"], "running")
            self.assertTrue(started["url"].startswith(BASE_URL))
            release.set()
            finished = await self._ok(
                "get_eval_run", {"run_id": started["run_id"], "wait_seconds": 5}
            )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["models"], [{"model": "gpt-4o", "passed": 0, "total": 0}])

    async def test_a_cancelled_turn_stops_waiting(self) -> None:
        saved = await self._prompt_suite()
        cancel = Event()
        cancel.set()
        cancelled_tools = self._tools(self.owner, cancel)
        release = asyncio.Event()

        async def slow(*, run_id: uuid.UUID, **_kwargs: Any) -> None:
            await release.wait()
            async with async_session_maker() as session:
                run = await session.get(EvalRun, run_id)
                run.status = "completed"
                await session.commit()

        args = {
            "suite_id": saved["suite"]["id"],
            "credential_id": str(self.credential_id),
            "models": ["gpt-4o"],
        }
        with patch.object(eval_service, "execute_evals_for_run", AsyncMock(side_effect=slow)):
            started = await self._ok("run_eval_suite", args, cancelled_tools)
            self.assertEqual(started["status"], "running")
            release.set()
            # The run keeps going without the turn; let it finish before teardown.
            finished = await self._ok(
                "get_eval_run", {"run_id": started["run_id"], "wait_seconds": 5}
            )
        self.assertEqual(finished["status"], "completed")

    async def test_an_agent_baseline_from_a_chat_run(self) -> None:
        created = await self._agent_suite()
        suite_id = created["suite"]["id"]
        self.assertEqual(created["baseline"]["source"], "latest_runs")
        self.assertEqual(created["baseline"]["run_count"], 3)
        self.assertEqual(created["input_fields"], ["text"])

        executor = AsyncMock(side_effect=[self._execution_result(t) for t in self.run_trace_ids])
        inputs = [{"text": "Where is my order?"}, {"text": "Cancel my plan"}]
        with patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor):
            run = await self._ok("run_eval_suite", {"suite_id": suite_id, "inputs": inputs})
        self.assertEqual([call.args[3] for call in executor.await_args_list], inputs)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["execution_statuses"], {"success": 2})
        self.assertEqual((run["report"]["run_count"], run["report"]["passed_count"]), (2, 2))

        rebased = await self._ok(
            "save_agent_suite",
            {"suite_id": suite_id, "baseline": {"source": "suite_run", "run_id": run["run_id"]}},
        )
        self.assertEqual(rebased["baseline"]["source"], "suite_run")
        self.assertEqual(rebased["baseline"]["run_count"], 2)
        self.assertEqual(rebased["baseline"]["latency_p95_ms"], 3000)
        self.assertEqual(rebased["suggested_thresholds"]["latency_ms"], 3600)

    async def test_a_manual_baseline_and_the_baseline_report(self) -> None:
        created = await self._agent_suite()
        suite_id = created["suite"]["id"]
        manual = await self._ok(
            "save_agent_suite",
            {
                "suite_id": suite_id,
                "baseline": {
                    "source": "manual",
                    "values": {"latency_p95_ms": 2500, "cost_avg_usd": 0.01},
                },
            },
        )
        baseline = manual["baseline"]
        self.assertEqual(
            (baseline["source"], baseline["latency_p95_ms"], baseline["cost_avg_usd"]),
            ("manual", 2500, 0.01),
        )
        report = await self._ok(
            "get_agent_baseline", {"workflow_id": str(self.workflow_id), "node_id": AGENT_NODE}
        )
        self.assertEqual(report["run_count"], 3)
        self.assertEqual(report["suggested_thresholds"]["tool_calls"], 1)
        agents = await self._ok("list_eval_agents", {})
        self.assertEqual(
            [(agent["node_id"], agent["run_count"]) for agent in agents["agents"]],
            [(AGENT_NODE, 3)],
        )
        error = await self._error(
            "save_agent_suite",
            {"suite_id": suite_id, "baseline": {"source": "manual", "values": {}}},
        )
        self.assertIn("at least one baseline value", error)

    async def test_an_agent_run_needs_inputs(self) -> None:
        created = await self._agent_suite()
        error = await self._error("run_eval_suite", {"suite_id": created["suite"]["id"]})
        self.assertIn("one input object per run", error)

    async def test_models_are_listed_for_reachable_credentials_only(self) -> None:
        listed = AsyncMock(return_value=[LLMModel(id="gpt-4o", name="GPT-4o")])
        with patch.object(chat_evals, "list_credential_models", listed):
            models = await self._ok("list_llm_models", {"credential_id": str(self.credential_id)})
            error = await self._error(
                "list_llm_models", {"credential_id": str(self.outsider_credential_id)}
            )
        self.assertEqual(models["models"], ["gpt-4o"])
        self.assertEqual(error, "Credential not found")

    async def test_another_user_reaches_nothing(self) -> None:
        prompt = await self._prompt_suite()
        agent = await self._agent_suite()
        outsider = self._tools(SimpleNamespace(id=self.outsider_id))
        calls = (
            ("get_eval_suite", {"suite_id": prompt["suite"]["id"]}),
            ("save_prompt_suite", {"suite_id": prompt["suite"]["id"], "name": "mine"}),
            ("run_eval_suite", {"suite_id": agent["suite"]["id"], "inputs": [{"text": "x"}]}),
            ("save_agent_suite", {"suite_id": agent["suite"]["id"], "name": "mine"}),
            (
                "get_agent_baseline",
                {"workflow_id": str(self.workflow_id), "node_id": AGENT_NODE},
            ),
        )
        for name, args in calls:
            with self.subTest(tool=name):
                error = await self._error(name, args, outsider)
                self.assertIn("not found", error)
        listed = await self._ok("list_eval_suites", {}, outsider)
        self.assertEqual(listed["count"], 0)

    def test_display_args_count_long_lists(self) -> None:
        shown = self.tools.display_args(
            "save_prompt_suite", {"name": "x", "test_cases": [{}, {}], "system_prompt": "p" * 500}
        )
        self.assertEqual(shown["test_cases"], 2)
        self.assertLessEqual(len(shown["system_prompt"]), 200)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_chat_evals.py -v`
Expected: `ImportError: cannot import name 'chat_evals' from 'app.api'`

- [ ] **Step 3: Create `backend/app/api/chat_evals.py`**

```python
"""Eval suite tools in the dashboard chat: create, change and run prompt and agent suites.

`ChatBuildSession` offers these tools on build turns (Chat tab, MCP `heym_chat`, Heym Work
Chat) and hands their calls here; MCP clients never see them in `tools/list`. Every
operation goes through the same functions as the Evals routes, so a suite made in chat is
the suite the Evals tab shows. Each call opens its own database session: a refused change
is dropped with it and never reaches the rest of the turn.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from threading import Event
from typing import Any, get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_suite_runs import AgentSuiteBusyError, launch_agent_suite_run
from app.api.credentials import list_credential_models
from app.api.workflows import _spawn_detached_task
from app.db.models import User
from app.db.session import async_session_maker
from app.models.agent_suite_schemas import (
    AgentBaselineValues,
    AgentSuiteCreate,
    AgentSuiteRunCreate,
    AgentSuiteRunResponse,
    AgentSuiteUpdate,
    ToolKind,
)
from app.models.eval_schemas import (
    EvalSuiteCreate,
    EvalSuiteUpdate,
    EvalTestCaseUpsert,
    RunEvalsRequest,
)
from app.services import agent_suite_service as agent_suites
from app.services import prompt_suite_service as prompt_suites
from app.services.agent_suite_inputs import MAX_SUITE_RUNS
from app.services.agent_suite_metrics import (
    DEFAULT_RUN_LIMIT,
    MAX_RUN_LIMIT,
    baseline_from_json,
    list_agent_nodes,
    suggest_thresholds,
)
from app.services.chat_build_mode import BuildToolOutcome, tool_error, truncate_text
from app.services.chat_eval_mode import (
    EVAL_TOOL_NAMES,
    GET_AGENT_BASELINE_TOOL,
    GET_EVAL_RUN_TOOL,
    GET_EVAL_SUITE_TOOL,
    GET_RUN_DEFAULT_WAIT_SECONDS,
    GET_RUN_MAX_WAIT_SECONDS,
    LIST_EVAL_AGENTS_TOOL,
    LIST_EVAL_SUITES_TOOL,
    LIST_LLM_MODELS_TOOL,
    MAX_MODELS_SHOWN,
    MAX_TEST_CASES_SHOWN,
    RUN_EVAL_SUITE_TOOL,
    RUN_POLL_SECONDS,
    RUN_WAIT_SECONDS,
    SAVE_AGENT_SUITE_TOOL,
    SAVE_PROMPT_SUITE_TOOL,
    STEP_LABELS,
    compact_baseline,
    error_text,
    list_arg,
    number_arg,
    optional_uuid_arg,
    parse_uuid,
    step_summary,
    suite_url,
    summarize_agent_run,
    summarize_prompt_run,
    uuid_arg,
    without_none,
)
from app.services.credential_access import get_accessible_credential
from app.services.eval_common import EvalNotFoundError
from app.services.prompt_suite_service import SCORING_METHODS, SuiteType

# The prompt run settings the chat may pass through to RunEvalsRequest.
RUN_FIELDS = (
    "credential_id",
    "models",
    "temperature",
    "reasoning_effort",
    "max_tokens",
    "runs_per_test",
    "judge_credential_id",
    "judge_model",
)

_ID: dict[str, Any] = {"type": "string"}
_SCORING: dict[str, Any] = {
    "type": "string",
    "enum": list(SCORING_METHODS),
    "description": "exact_match for fixed labels, contains for key facts, llm_judge for free text.",
}


def _function(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


EVAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _function(
        LIST_EVAL_SUITES_TOOL,
        "List the user's eval suites, prompt and agent, most recently updated first, with "
        "their links.",
        {},
    ),
    _function(
        GET_EVAL_SUITE_TOOL,
        "Read one eval suite. A prompt suite returns its system prompt, scoring method, test "
        "cases with their ids and its latest runs. An agent suite returns its agent, "
        "assertions, thresholds, stored baseline, the workflow's input_fields with the last "
        "run's previous_inputs, and its latest run.",
        {"suite_id": {**_ID, "description": "Id from list_eval_suites or a save result."}},
        ["suite_id"],
    ),
    _function(
        LIST_EVAL_AGENTS_TOOL,
        "List the agent nodes in the user's workflows with how many runs each has, to choose "
        "the agent of an agent suite.",
        {},
    ),
    _function(
        GET_AGENT_BASELINE_TOOL,
        "Read an agent's baseline from its latest runs: latency, cost, tokens and tool calls, "
        "how often each tool was called, and thresholds suggested 20% above the baseline.",
        {
            "workflow_id": {**_ID},
            "node_id": {"type": "string", "description": "The agent node's id."},
            "limit": {
                "type": "integer",
                "description": f"How many latest runs to read, 1 to {MAX_RUN_LIMIT}. "
                f"Default {DEFAULT_RUN_LIMIT}.",
            },
        },
        ["workflow_id", "node_id"],
    ),
    _function(
        LIST_LLM_MODELS_TOOL,
        "List the models an LLM credential offers, to choose the models a prompt suite compares.",
        {"credential_id": {**_ID, "description": "An LLM credential from the Credentials list."}},
        ["credential_id"],
    ),
    _function(
        SAVE_PROMPT_SUITE_TOOL,
        "Create a prompt eval suite, or change one when suite_id is given. When changing, pass "
        "only what changes.",
        {
            "suite_id": {**_ID, "description": "The suite to change. Omit it to create one."},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "system_prompt": {
                "type": "string",
                "description": "The prompt every test case runs against.",
            },
            "scoring_method": _SCORING,
            "test_cases": {
                "type": "array",
                "description": "Cases to add (no id) or change (id from get_eval_suite).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "input": {"type": "string"},
                        "expected_output": {"type": "string"},
                    },
                },
            },
            "delete_test_case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ids of cases to remove.",
            },
        },
    ),
    _function(
        SAVE_AGENT_SUITE_TOOL,
        "Create an agent eval suite for one agent node, or change one when suite_id is given. "
        "When changing, pass only what changes. The result has the stored baseline and the "
        "thresholds suggested from it.",
        {
            "suite_id": {**_ID, "description": "The suite to change. Omit it to create one."},
            "name": {"type": "string"},
            "workflow_id": {**_ID, "description": "The agent's workflow, when creating."},
            "node_id": {"type": "string", "description": "The agent node, when creating."},
            "tool_assertions": {
                "type": "array",
                "description": "Every tool check; it replaces the stored list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(get_args(ToolKind))},
                        "name": {
                            "type": "string",
                            "description": "A tool's name, a sub-agent's label or a "
                            "sub-workflow's id.",
                        },
                        "label": {"type": "string"},
                        "expect": {"type": "string", "enum": ["called", "not_called"]},
                    },
                    "required": ["name", "expect"],
                },
            },
            "thresholds": {
                "type": "object",
                "description": "Upper bounds per run; leave one out to turn that check off. "
                "It replaces the stored thresholds.",
                "properties": {
                    "latency_ms": {"type": "number"},
                    "cost_usd": {"type": "number"},
                    "total_tokens": {"type": "integer"},
                    "tool_calls": {"type": "integer"},
                },
            },
            "baseline": {
                "type": "object",
                "description": "Where the baseline comes from: latest_runs (the agent's last "
                "runs), suite_run (one finished run of this suite, by run_id) or manual "
                "(values the user stated).",
                "properties": {
                    "source": {"type": "string", "enum": ["latest_runs", "suite_run", "manual"]},
                    "run_id": {**_ID},
                    "values": {
                        "type": "object",
                        "properties": {
                            key: {"type": "number"} for key in AgentBaselineValues.model_fields
                        },
                    },
                },
                "required": ["source"],
            },
        },
    ),
    _function(
        RUN_EVAL_SUITE_TOOL,
        f"Run an eval suite and wait up to {int(RUN_WAIT_SECONDS)} seconds for the result. A "
        "prompt suite needs credential_id and models. An agent suite needs inputs, one object "
        "per run, and runs the real workflow.",
        {
            "suite_id": {**_ID},
            "credential_id": {
                **_ID,
                "description": "Prompt suites: the LLM credential the models run on.",
            },
            "models": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prompt suites: the models to compare.",
            },
            "scoring_method": {**_SCORING, "description": "Prompt suites: defaults to the suite's."},
            "judge_credential_id": {
                **_ID,
                "description": "llm_judge: a separate judge's credential. Omit it to let each "
                "model score its own answer.",
            },
            "judge_model": {"type": "string"},
            "runs_per_test": {"type": "integer", "description": "Prompt suites: 1 to 20."},
            "temperature": {"type": "number"},
            "inputs": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Agent suites: one input object per run, keyed by input_fields, "
                f"at most {MAX_SUITE_RUNS}.",
            },
        },
        ["suite_id"],
    ),
    _function(
        GET_EVAL_RUN_TOOL,
        "Check a run that run_eval_suite started, waiting up to wait_seconds (at most "
        f"{int(GET_RUN_MAX_WAIT_SECONDS)}) for it to finish.",
        {"run_id": {**_ID}, "wait_seconds": {"type": "integer"}},
        ["run_id"],
    ),
]

ToolHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]


class ChatEvalTools:
    """The eval tools of one chat turn."""

    def __init__(self, *, user: User, public_base_url: str, cancel_event: Event | None) -> None:
        self.user = user
        self.public_base_url = public_base_url
        self.cancel_event = cancel_event
        self.run_wait_seconds = RUN_WAIT_SECONDS
        self.poll_seconds = RUN_POLL_SECONDS
        self._handlers: dict[str, ToolHandler] = {
            LIST_EVAL_SUITES_TOOL: self._list_suites,
            GET_EVAL_SUITE_TOOL: self._get_suite,
            LIST_EVAL_AGENTS_TOOL: self._list_agents,
            GET_AGENT_BASELINE_TOOL: self._agent_baseline,
            LIST_LLM_MODELS_TOOL: self._list_models,
            SAVE_PROMPT_SUITE_TOOL: self._save_prompt_suite,
            SAVE_AGENT_SUITE_TOOL: self._save_agent_suite,
            RUN_EVAL_SUITE_TOOL: self._run_suite,
            GET_EVAL_RUN_TOOL: self._get_run,
        }

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return list(EVAL_TOOL_SCHEMAS)

    def handles(self, name: str) -> bool:
        return name in EVAL_TOOL_NAMES

    def step_label(self, name: str) -> str:
        return STEP_LABELS[name]

    def display_args(self, _name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Arguments for the step row and the trace, with long lists counted, not copied."""
        shown = dict(args)
        for key in ("test_cases", "delete_test_case_ids", "inputs"):
            if isinstance(shown.get(key), list):
                shown[key] = len(shown[key])
        if isinstance(shown.get("system_prompt"), str):
            shown["system_prompt"] = truncate_text(shown["system_prompt"], 200)
        return shown

    async def call(self, name: str, args: dict[str, Any]) -> BuildToolOutcome:
        try:
            async with async_session_maker() as db:
                payload = await self._handlers[name](db, args)
        except (EvalNotFoundError, AgentSuiteBusyError, ValueError) as exc:
            return tool_error(error_text(exc))
        return BuildToolOutcome(
            result=json.dumps(payload, default=str),
            summary=step_summary(name, payload),
            status="success",
        )

    def _url(self, suite_id: object) -> str:
        return suite_url(self.public_base_url, suite_id)

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    async def _list_suites(self, db: AsyncSession, _args: dict[str, Any]) -> dict[str, Any]:
        suites = await prompt_suites.list_all_suites(db, self.user.id)
        return {
            "count": len(suites),
            "suites": [
                {
                    "id": str(suite.id),
                    "name": suite.name,
                    "suite_type": suite.suite_type,
                    "url": self._url(suite.id),
                }
                for suite in suites
            ],
        }

    async def _get_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = uuid_arg(args, "suite_id")
        if await prompt_suites.owned_suite_type(db, suite_id, self.user.id) == "prompt":
            return await self._prompt_suite_payload(db, suite_id, include_runs=True)
        return await self._agent_suite_payload(db, suite_id)

    async def _prompt_suite_payload(
        self, db: AsyncSession, suite_id: uuid.UUID, *, include_runs: bool
    ) -> dict[str, Any]:
        suite = await prompt_suites.load_owned_prompt_suite(
            db, suite_id, self.user.id, with_test_cases=True
        )
        cases = suite.test_cases
        described: dict[str, Any] = {
            "id": str(suite.id),
            "name": suite.name,
            "suite_type": "prompt",
            "description": suite.description,
            "system_prompt": suite.system_prompt,
            "scoring_method": suite.scoring_method,
            "test_cases": [
                {"id": str(tc.id), "input": tc.input, "expected_output": tc.expected_output}
                for tc in cases[:MAX_TEST_CASES_SHOWN]
            ],
        }
        if len(cases) > MAX_TEST_CASES_SHOWN:
            described["test_cases_omitted"] = len(cases) - MAX_TEST_CASES_SHOWN
        payload: dict[str, Any] = {"suite": described, "url": self._url(suite.id)}
        if include_runs:
            runs = await prompt_suites.list_prompt_runs(db, suite.id, self.user.id)
            payload["latest_runs"] = [
                {
                    "run_id": str(run.id),
                    "name": run.name,
                    "status": run.status,
                    "models": run.models,
                    "passed": run.pass_count,
                    "total": run.total_count,
                }
                for run in runs[:3]
            ]
        return payload

    async def _agent_suite_payload(self, db: AsyncSession, suite_id: uuid.UUID) -> dict[str, Any]:
        suite = await agent_suites.get_agent_suite(db, self.user.id, suite_id)
        inputs = await agent_suites.agent_run_inputs(db, self.user.id, suite_id)
        latest = await agent_suites.latest_agent_suite_run(db, suite_id)
        payload: dict[str, Any] = {
            "suite": {
                "id": str(suite.id),
                "name": suite.name,
                "suite_type": "agent",
                "workflow_id": str(suite.workflow_id),
                "workflow_name": suite.workflow_name,
                "node_id": suite.node_id,
                "node_label": suite.node_label,
                "tool_assertions": [
                    without_none(assertion.model_dump()) for assertion in suite.tool_assertions
                ],
                "thresholds": without_none(suite.thresholds.model_dump()),
            },
            "baseline": compact_baseline(suite.baseline),
            "input_fields": inputs.fields,
            "previous_inputs": inputs.previous_inputs,
            "url": self._url(suite.id),
        }
        if latest is not None:
            payload["latest_run"] = {
                "run_id": str(latest.id),
                "status": latest.status,
                "runs": latest.requested_count,
            }
        return payload

    async def _list_agents(self, db: AsyncSession, _args: dict[str, Any]) -> dict[str, Any]:
        agents = await list_agent_nodes(db, user_id=self.user.id)
        return {
            "count": len(agents),
            "agents": [
                {
                    "workflow_id": str(agent.workflow_id),
                    "workflow_name": agent.workflow_name,
                    "node_id": agent.node_id,
                    "node_label": agent.node_label,
                    "run_count": agent.run_count,
                    "last_run_at": agent.last_run_at.isoformat() if agent.last_run_at else None,
                }
                for agent in agents
            ],
        }

    async def _agent_baseline(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(
            number_arg(args, "limit", default=DEFAULT_RUN_LIMIT, low=1, high=MAX_RUN_LIMIT)
        )
        metrics = await agent_suites.agent_metrics(
            db, self.user.id, uuid_arg(args, "workflow_id"), str(args.get("node_id") or ""), limit
        )
        return {
            "workflow_name": metrics.workflow_name,
            "node_label": metrics.node_label,
            "run_count": len(metrics.runs),
            "baseline": compact_baseline(metrics.baseline),
            "tools": [without_none(tool.model_dump()) for tool in metrics.tools],
            "suggested_thresholds": without_none(metrics.suggested_thresholds.model_dump()),
        }

    async def _list_models(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        credential = await get_accessible_credential(
            db, uuid_arg(args, "credential_id"), self.user.id
        )
        if credential is None:
            raise EvalNotFoundError("Credential not found")
        models = await list_credential_models(credential)
        return {
            "credential": credential.name,
            "models": [model.id for model in models][:MAX_MODELS_SHOWN],
        }

    async def _save_prompt_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = optional_uuid_arg(args, "suite_id")
        upserts = [EvalTestCaseUpsert.model_validate(item) for item in list_arg(args, "test_cases")]
        delete_ids = [
            parse_uuid(item, "delete_test_case_ids")
            for item in list_arg(args, "delete_test_case_ids")
        ]
        fields = {
            key: args.get(key) for key in ("name", "description", "system_prompt", "scoring_method")
        }
        if suite_id is None:
            if delete_ids or any(upsert.id is not None for upsert in upserts):
                raise ValueError("A new suite has no test cases to change or delete yet")
            suite = await prompt_suites.create_prompt_suite(
                db, self.user.id, EvalSuiteCreate.model_validate(without_none(fields))
            )
            if upserts:
                await prompt_suites.apply_test_case_changes(db, suite, upserts, [])
            return await self._prompt_suite_payload(db, suite.id, include_runs=False)
        update = EvalSuiteUpdate.model_validate(fields)
        # Check everything before the first commit, so a refused edit changes nothing.
        prompt_suites.check_scoring_method(update.scoring_method)
        suite = await prompt_suites.load_owned_prompt_suite(
            db, suite_id, self.user.id, with_test_cases=True
        )
        if upserts or delete_ids:
            suite = await prompt_suites.apply_test_case_changes(db, suite, upserts, delete_ids)
        await prompt_suites.update_prompt_suite(db, suite, update)
        return await self._prompt_suite_payload(db, suite.id, include_runs=False)

    async def _save_agent_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = optional_uuid_arg(args, "suite_id")
        fields = without_none(
            {
                key: args.get(key)
                for key in ("name", "tool_assertions", "thresholds", "baseline")
            }
        )
        if suite_id is None:
            body = AgentSuiteCreate.model_validate(
                {**fields, "workflow_id": args.get("workflow_id"), "node_id": args.get("node_id")}
            )
            suite = await agent_suites.create_agent_suite(db, self.user.id, body)
        else:
            suite = await agent_suites.update_agent_suite(
                db, self.user.id, suite_id, AgentSuiteUpdate.model_validate(fields)
            )
        payload = await self._agent_suite_payload(db, suite.id)
        suggested = suggest_thresholds(baseline_from_json(suite.baseline.model_dump()))
        payload["suggested_thresholds"] = without_none(asdict(suggested))
        return payload

    async def _run_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = uuid_arg(args, "suite_id")
        suite_type = await prompt_suites.owned_suite_type(db, suite_id, self.user.id)
        if suite_type == "prompt":
            suite = await prompt_suites.load_owned_prompt_suite(db, suite_id, self.user.id)
            body = RunEvalsRequest.model_validate(
                {
                    **without_none({key: args.get(key) for key in RUN_FIELDS}),
                    "scoring_method": args.get("scoring_method") or suite.scoring_method,
                }
            )
            launch = await prompt_suites.launch_prompt_run(db, self.user, suite_id, body)
            run_id, job = launch.run.id, launch.job
        else:
            inputs = list_arg(args, "inputs")
            if not inputs:
                raise ValueError(
                    f"Write one input object per run in inputs, at most {MAX_SUITE_RUNS}."
                )
            agent_suite = await agent_suites.load_owned_agent_suite(db, suite_id, self.user.id)
            agent_launch = await launch_agent_suite_run(
                db,
                self.user.id,
                agent_suite,
                AgentSuiteRunCreate.model_validate({"inputs_list": inputs}),
                self.public_base_url,
            )
            run_id, job = agent_launch.suite_run.id, agent_launch.job
        _spawn_detached_task(job.coroutine())
        return await self._wait(suite_type, run_id, self.run_wait_seconds)

    async def _get_run(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid_arg(args, "run_id")
        wait = number_arg(
            args,
            "wait_seconds",
            default=GET_RUN_DEFAULT_WAIT_SECONDS,
            low=0,
            high=GET_RUN_MAX_WAIT_SECONDS,
        )
        return await self._wait(await self._owned_run_type(db, run_id), run_id, wait)

    async def _owned_run_type(self, db: AsyncSession, run_id: uuid.UUID) -> SuiteType:
        try:
            await prompt_suites.load_owned_prompt_run(db, run_id, self.user.id)
            return "prompt"
        except EvalNotFoundError:
            await agent_suites.load_owned_agent_suite_run(db, run_id, self.user.id)
            return "agent"

    async def _wait(
        self, suite_type: SuiteType, run_id: uuid.UUID, seconds: float
    ) -> dict[str, Any]:
        """Poll the run with a fresh session until it ends, the time is up or the turn stops."""
        deadline = time.monotonic() + seconds
        while True:
            async with async_session_maker() as db:
                payload = await self._run_state(db, suite_type, run_id)
            if (
                payload["status"] != "running"
                or time.monotonic() >= deadline
                or self._cancelled()
            ):
                return payload
            await asyncio.sleep(self.poll_seconds)

    async def _run_state(
        self, db: AsyncSession, suite_type: SuiteType, run_id: uuid.UUID
    ) -> dict[str, Any]:
        if suite_type == "prompt":
            run = await prompt_suites.load_owned_prompt_run(db, run_id, self.user.id)
            url = self._url(run.suite_id)
            if run.status == "running":
                return {
                    "run_id": str(run.id),
                    "suite_type": "prompt",
                    "status": "running",
                    "results_so_far": len(run.results),
                    "url": url,
                }
            response = prompt_suites.prompt_run_response(run, run.results)
            return {**summarize_prompt_run(response), "url": url}
        suite_run = await agent_suites.load_owned_agent_suite_run(db, run_id, self.user.id)
        report = None
        if suite_run.status != "running":
            report = await agent_suites.agent_suite_report(
                db, self.user.id, suite_run.suite_id, MAX_RUN_LIMIT, suite_run.id
            )
        response = AgentSuiteRunResponse.model_validate(suite_run)
        return {**summarize_agent_run(response, report), "url": self._url(suite_run.suite_id)}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_chat_evals.py -v && uv run ruff check app/api/chat_evals.py && uv run ruff format --check app/api/chat_evals.py`
Expected: 13 passed, then `All checks passed!` and `1 file already formatted`. If the format check fails, run `uv run ruff format app/api/chat_evals.py`, then run the tests again.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/chat_evals.py backend/tests/test_chat_evals.py
git commit -m "feat(chat): create, edit and run eval suites from chat"
```

---

### Task 8: Offer the eval tools on build turns

**Files:**
- Modify: `backend/app/api/chat_build.py` (`__init__`, `prompt`, `tools`, `handles`, `display_args`, `step_label`, `call`)
- Test: `backend/tests/test_chat_build_session.py`, `backend/tests/test_chat_build_stream.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_chat_build_session.py`:

- Add these imports: `from app.services.chat_build_mode import BuildToolOutcome` and `from app.services.chat_eval_mode import EVAL_TOOL_NAMES`.
- Add `self.assertIn("## Eval suites", prompt)` to `test_prompt_adds_instructions_target_and_dsl_reference`.
- Add these two methods to `ChatBuildSessionTests`:

```python
    async def test_build_turns_offer_the_eval_tools_and_hand_them_over(self) -> None:
        session = self._session()
        names = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertTrue(EVAL_TOOL_NAMES <= set(names))
        self.assertEqual(names[-3:], ["save_workflow", "run_workflow_test", "finish"])
        self.assertTrue(session.handles("run_eval_suite"))
        self.assertEqual(session.step_label("save_prompt_suite"), "Saving the prompt suite...")
        self.assertEqual(
            session.display_args("save_prompt_suite", {"name": "x", "test_cases": [{}, {}]}),
            {"name": "x", "test_cases": 2},
        )
        outcome = BuildToolOutcome(result="{}", summary="2 suites", status="success")
        with patch.object(session.evals, "call", AsyncMock(return_value=outcome)) as call:
            self.assertIs(await session.call("list_eval_suites", {}), outcome)
        call.assert_awaited_once_with("list_eval_suites", {})

    async def test_skill_only_turns_get_no_eval_tools(self) -> None:
        session = chat_build.ChatBuildSession(
            db=self.db,
            user=self.user,
            request=BuildRequest(skill_only=True),
            selected_credential=SimpleNamespace(id=uuid.uuid4(), owner_id=self.user.id, type="openai"),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id="conv-1",
        )
        names = {t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)}
        self.assertFalse(EVAL_TOOL_NAMES & names)
        self.assertFalse(session.handles("save_prompt_suite"))
        self.assertIsNone(session.evals)
```

In `backend/tests/test_chat_build_stream.py`, import `EVAL_TOOL_NAMES` from `app.services.chat_eval_mode`. Then add this line at the end of `test_without_build_mode_the_build_tools_are_not_offered`:

```python
        self.assertFalse(EVAL_TOOL_NAMES & set(names))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_chat_build_session.py -v -k "eval or prompt_adds"`
Expected: FAIL, `AttributeError: 'ChatBuildSession' object has no attribute 'evals'`

- [ ] **Step 3: Wire `ChatEvalTools` into `ChatBuildSession`**

In `backend/app/api/chat_build.py`:

1. Add the imports `from app.api.chat_evals import ChatEvalTools` and `from app.services.chat_eval_mode import eval_instructions`.
2. In `__init__`, after `self.progress = ...`:

```python
        # Eval suites are part of every build turn; a skill-only turn writes skills only.
        self.evals = (
            None
            if request.skill_only
            else ChatEvalTools(
                user=user, public_base_url=public_base_url, cancel_event=cancel_event
            )
        )
```

3. In `prompt()`, change the final return to:

```python
        return (
            f"{instructions}\n{eval_instructions()}\n{skill_block}\n"
            f"## Workflow DSL reference\n\n{reference}"
        )
```

4. In `tools()`, directly after `if self.request.skill_only: return tools + [APPLY_SKILL_TOOL_SCHEMA]`:

```python
        if self.evals is not None:
            tools += self.evals.schemas()
```

5. In `handles()`, directly after the `if self.request.skill_only:` return:

```python
        if self.evals is not None and self.evals.handles(name):
            return True
```

6. At the top of `display_args()` and of `step_label()`:

```python
        if self.evals is not None and self.evals.handles(name):
            return self.evals.display_args(name, args)
```

```python
        if self.evals is not None and self.evals.handles(name):
            return self.evals.step_label(name)
```

7. In `call()`, directly after `if self.request.skill_only: return tool_error(...)`:

```python
        if self.evals is not None and self.evals.handles(name):
            return await self.evals.call(name, args)
```

- [ ] **Step 4: Run every chat build test**

Run: `uv run pytest tests/test_chat_build_session.py tests/test_chat_build_stream.py tests/test_chat_build_mcp.py tests/test_chat_build_api.py tests/test_chat_build_mode.py -v && uv run ruff check app/api/chat_build.py`
Expected: all pass, and `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/chat_build.py backend/tests/test_chat_build_session.py \
  backend/tests/test_chat_build_stream.py
git commit -m "feat(chat): offer eval suite tools on build turns"
```

---

### Task 9: MCP `heym_chat` names the capability; MCP clients see no eval tool

**Files:**
- Modify: `backend/app/services/mcp_chat_service.py` (`MCP_CHAT_TOOL_DESCRIPTION`)
- Test: `backend/tests/test_mcp_chat_tool.py` (`ChatToolExposureTests`)

- [ ] **Step 1: Write the failing test**

Add `from app.services.chat_eval_mode import EVAL_TOOL_NAMES` to the imports. Add this to `ChatToolExposureTests`:

```python
    async def test_eval_tools_stay_inside_heym_chat(self) -> None:
        """The global server and named servers share build_tools_with_chat."""
        settings = MCPChatSettings(enabled=True, credential_id=uuid.uuid4(), model="gpt-5")

        with patch(
            "app.api.mcp.workflow_to_mcp_tool", side_effect=lambda w: SimpleNamespace(name=w.name)
        ):
            tools = await build_tools_with_chat([_make_workflow()], settings)

        self.assertFalse(EVAL_TOOL_NAMES & {t.name for t in tools})
        self.assertIn("eval suites", mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_mcp_chat_tool.py -v -k eval_tools`
Expected: FAIL on `assertIn("eval suites", ...)`

- [ ] **Step 3: Extend the description**

In `MCP_CHAT_TOOL_DESCRIPTION`, after the sentence part `"... and fix it until a run passes; "`, insert:

```python
    "create, edit and run prompt and agent eval suites, including an agent's baseline; "
```

- [ ] **Step 4: Run the MCP tests**

Run: `uv run pytest tests/test_mcp_chat_tool.py tests/test_advisory_mcp_chat_workflow_links.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/mcp_chat_service.py backend/tests/test_mcp_chat_tool.py
git commit -m "feat(mcp): heym_chat describes eval suites"
```

---

### Task 10: The Evals UI shows where a baseline came from

**Files:**
- Modify: `frontend/src/types/evals.ts`
- Modify: `frontend/src/components/Evals/AgentSuite/agentSuiteFormat.ts`
- Modify: `frontend/src/components/Evals/AgentSuite/AgentSuiteChecksStep.vue:8,107-109`
- Test: `frontend/src/components/Evals/AgentSuite/agentSuiteFormat.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Evals/AgentSuite/agentSuiteFormat.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { baselineSourceLabel } from "@/components/Evals/AgentSuite/agentSuiteFormat";

describe("baselineSourceLabel", () => {
  it("names each source", () => {
    expect(baselineSourceLabel({ source: "manual" })).toBe("entered manually");
    expect(baselineSourceLabel({ source: "suite_run" })).toBe("from a suite run");
    expect(baselineSourceLabel({ source: "latest_runs" })).toBe("from the latest runs");
  });

  it("reads a baseline saved before sources existed as the latest runs", () => {
    expect(baselineSourceLabel({})).toBe("from the latest runs");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && bun run test src/components/Evals/AgentSuite/agentSuiteFormat.test.ts`
Expected: FAIL, `baselineSourceLabel is not a function` (or not exported)

- [ ] **Step 3: Types, helper and label**

In `frontend/src/types/evals.ts`:

- Add above `export interface AgentBaseline`:

```ts
export type AgentBaselineSourceKind = "latest_runs" | "suite_run" | "manual";
```

- Add to `AgentBaseline`, after `captured_at`:

```ts
  source?: AgentBaselineSourceKind;
  suite_run_id?: string | null;
```

- Add after `AgentBaseline`:

```ts
export interface AgentBaselineValues {
  latency_p50_ms?: number | null;
  latency_p95_ms?: number | null;
  cost_avg_usd?: number | null;
  cost_p95_usd?: number | null;
  tokens_avg?: number | null;
  tokens_p95?: number | null;
  tool_calls_avg?: number | null;
  tool_calls_max?: number | null;
}

export interface AgentBaselineSourceRequest {
  source: AgentBaselineSourceKind;
  run_id?: string | null;
  values?: AgentBaselineValues | null;
}
```

- Add `baseline?: AgentBaselineSourceRequest;` to both `CreateAgentSuiteRequest` and `UpdateAgentSuiteRequest`.
- Add `inputs_list?: Record<string, unknown>[] | null;` to `CreateAgentSuiteRunRequest`.

In `frontend/src/components/Evals/AgentSuite/agentSuiteFormat.ts`:

- Change the type import to `import type { AgentBaseline, AgentThresholds, ToolKind } from "@/types/evals";`.
- Add:

```ts
/** Where a saved baseline came from; one saved before sources existed is the latest runs. */
export function baselineSourceLabel(baseline: Pick<AgentBaseline, "source">): string {
  if (baseline.source === "manual") return "entered manually";
  if (baseline.source === "suite_run") return "from a suite run";
  return "from the latest runs";
}
```

In `AgentSuiteChecksStep.vue`:

- Add `baselineSourceLabel,` to the `agentSuiteFormat` import, keeping the names in alphabetical order.
- Replace the saved-baseline span with:

```vue
          <span v-if="savedBaseline.captured_at">
            Saved baseline: {{ formatRunTime(savedBaseline.captured_at) }} ·
            {{ baselineSourceLabel(savedBaseline) }}
          </span>
```

- [ ] **Step 4: Run frontend checks**

Run: `cd frontend && bun run test src/components/Evals/AgentSuite/agentSuiteFormat.test.ts && bun run lint && bun run typecheck`
Expected: 2 passed, no lint errors, no type errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/evals.ts frontend/src/components/Evals/AgentSuite/agentSuiteFormat.ts \
  frontend/src/components/Evals/AgentSuite/agentSuiteFormat.test.ts \
  frontend/src/components/Evals/AgentSuite/AgentSuiteChecksStep.vue
git commit -m "feat(evals): show where an agent suite's baseline came from"
```

---

### Task 11: Docs and the repository rule

**Files:**
- Modify: `frontend/src/docs/content/tabs/chat-tab.md` (new section before `## User Rules`)
- Modify: `frontend/src/docs/content/tabs/evals-tab.md` (end of `## Agent Suites`)
- Modify: `frontend/src/docs/content/tabs/mcp-tab.md` (capability list, line 58-68)
- Modify: `frontend/src/docs/content/reference/features.md` (Chat paragraph line 774, `heym_chat` paragraph line 811)
- Modify: `AGENTS.md` (`### Chat build mode`)

- [ ] **Step 1: `chat-tab.md`**

Insert before `## User Rules`:

```markdown
## Working with Evals

Chat can create, change and run the suites in [Evals](./evals-tab.md), both prompt suites and agent suites:

- **Prompt suite**: "make a prompt suite for my support reply prompt with 8 test cases and compare gpt-4o with gpt-4.1-mini". Chat writes the test cases with their expected answers, picks a scoring method and saves the suite.
  - Before it creates the suite, it settles which LLM credential and models to use. With exactly one LLM credential it uses that one and says so; otherwise it asks.
  - For LLM-as-Judge scoring, it also asks whether a separate judge should score the answers.
- **Agent suite**: "check that my support agent always searches the docs and never sends email". Chat finds the agent and saves the tool checks and thresholds. When you ask, it runs the workflow, writing a different input for each run.
  - Agent suite runs are real workflow runs, so their side effects happen. Chat says how many runs it starts.
- **Baseline**: Chat can work with an agent's baseline in three ways:
  - Report it from the agent's latest runs.
  - Build it from runs it starts ("run it 5 times and use that as the baseline").
  - Store numbers you give it ("set the baseline to 3 seconds p95 and $0.01 per run").
- **Runs**: Chat waits up to a minute for a run, then reports the result:
  - For a prompt suite: each model's pass count and the cases that failed.
  - For an agent suite: the pass rate, the failed checks and the drift from the baseline.
  - A longer run keeps going in Evals; ask Chat to check it again.

Every reply links the suite on the Evals page.

The same works from an MCP client through `heym_chat` (see [Using Chat from an MCP Client](#using-chat-from-an-mcp-client)). The eval tools stay inside `heym_chat`; MCP clients do not see them as separate tools.

The editor's AI Assistant does not create suites.
```

- [ ] **Step 2: `evals-tab.md`**

At the end of the "How the numbers are read" list in `## Agent Suites`, add:

```markdown

A suite's baseline comes from one of three places. **Edit checks** shows which one next to **Saved baseline**:

- the agent's latest runs (the default, and what **Use latest runs as baseline** takes),
- one finished suite run,
- numbers entered by hand.

The last two are set from [Chat](./chat-tab.md#working-with-evals) or the API:

- `PATCH /api/evals/agent-suites/{id}` takes `baseline: {"source": "suite_run", "run_id": "…"}` or `{"source": "manual", "values": {"latency_p95_ms": 3000, "cost_avg_usd": 0.01}}`.
- `POST /api/evals/agent-suites/{id}/runs` takes `inputs_list`: one input object per run, up to 20.

### From Chat and MCP

[Chat](./chat-tab.md#working-with-evals) and the MCP `heym_chat` tool can create, change and run prompt and agent suites:

- They write test cases and run inputs themselves.
- They ask which credential to use before creating a prompt suite, unless only one fits.
- They link every suite they mention on this page.
```

- [ ] **Step 3: `mcp-tab.md`**

In the `heym_chat` capability list, after the "List your data tables …" bullet, add:

```markdown
- Create, edit and run prompt and agent [eval suites](./evals-tab.md#from-chat-and-mcp), including an agent's baseline: reported, built from runs, or stated as numbers
```

Then, after the paragraph "Capabilities added to the Chat tab later …", add:

```markdown
These capabilities run inside `heym_chat`: `tools/list` shows `heym_chat` and your workflow tools, never the chat's internal tools such as the eval suite ones.
```

- [ ] **Step 4: `features.md`**

1. In the Chat paragraph (line 774), after "test-run them with sample inputs and fix them until a run passes,", insert "create, edit and run prompt and agent eval suites, including an agent's baseline,".
2. In the `heym_chat` paragraph (line 811), after "documentation search,", insert "prompt and agent eval suites,".

- [ ] **Step 5: `AGENTS.md`**

Under `### Chat build mode`, add a bullet after the `finish` bullet:

```markdown
- Build turns also carry the eval suite tools (`backend/app/api/chat_evals.py`); skill-only turns and the canvas assistant do not, and MCP `tools/list` never shows them. They call `prompt_suite_service.py`, `agent_suite_service.py` and `launch_agent_suite_run`, the same code as the Evals routes. Do not write eval rows anywhere else.
```

- [ ] **Step 6: Check the docs build and links**

Run: `cd frontend && bun run lint && bun run test src/docs`
Expected: no errors. If `src/docs` has no specs, Vitest reports "No test files found" and exits 0 or 1; that is acceptable. Then confirm the anchors exist:

```bash
grep -n "## Working with Evals" frontend/src/docs/content/tabs/chat-tab.md
grep -n "### From Chat and MCP" frontend/src/docs/content/tabs/evals-tab.md
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/docs/content AGENTS.md
git commit -m "docs: eval suites from Chat and MCP"
```

---

### Task 12: Release tour section

The current unreleased release is `2026.22` (the latest tag is `v0.0.138`, cut before #817). The registry keeps five sections, so adding one drops the oldest, `codex-device-sign-in`.

**Files:**
- Create: `frontend/src/features/release-tour/components/visuals/ChatEvalsTourVisual.vue`
- Delete: `frontend/src/features/release-tour/components/visuals/CodexSignInTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Modify: `frontend/src/features/release-tour/releaseTourMapper.test.ts:380-405`

- [ ] **Step 1: Update the registry test first**

In `releaseTourMapper.test.ts`:

- In "lists every shipped tour, newest first", set the expected slides to:

```ts
    expect(catalog?.slides.map((slide) => slide.id)).toEqual([
      "agent-suite",
      "chat-evals",
      "concurrency-limit",
      "canvas-collaboration",
      "node-ai-edit",
    ]);
```

- In "registers a visual for every section…", replace `.toContain("codex-device-sign-in")` with `.toContain("chat-evals")`.

Run: `cd frontend && bun run test src/features/release-tour`
Expected: FAIL on the slide list

- [ ] **Step 2: Create the visual**

`frontend/src/features/release-tour/components/visuals/ChatEvalsTourVisual.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { CheckCircle2, MessageSquare, XCircle } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the request · 1: the credential question · 2: the run reported back.
const step = useCycleStep(3, 2400);

interface MockLine {
  id: string;
  from: "user" | "assistant";
  text: string;
  state?: "pass" | "fail";
}

const request: MockLine = {
  id: "ask",
  from: "user",
  text: "Make a prompt suite for my support prompt and compare two models",
};

const lines = computed<MockLine[]>(() => {
  if (step.value === 0) {
    return [request, { id: "wrote", from: "assistant", text: "Wrote 5 test cases with expected answers" }];
  }
  if (step.value === 1) {
    return [request, { id: "which", from: "assistant", text: "Which credential? OpenAI · Work, or Gemini" }];
  }
  return [
    request,
    { id: "m1", from: "assistant", text: "gpt-4o · 5/5 passed", state: "pass" },
    { id: "m2", from: "assistant", text: "gpt-4.1-mini · 4/5 passed", state: "fail" },
  ];
});

const caption = computed<string>(
  () =>
    [
      "Chat writes the test cases",
      "It asks which credential to use",
      "Then runs the suite and reports back",
    ][step.value],
);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <MessageSquare class="h-3 w-3" />
      Chat · Evals
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1.5">
      <div
        v-for="line in lines"
        :key="line.id"
        class="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="line.from === 'user'
          ? 'ml-6 border-primary/40 bg-primary/10'
          : line.state === 'fail'
            ? 'mr-6 border-destructive/40 bg-destructive/10'
            : 'mr-6 border-border bg-background'"
      >
        <CheckCircle2
          v-if="line.state === 'pass'"
          class="h-3 w-3 shrink-0 text-emerald-500"
        />
        <XCircle
          v-else-if="line.state === 'fail'"
          class="h-3 w-3 shrink-0 text-destructive"
        />
        <span class="truncate text-foreground">{{ line.text }}</span>
      </div>
    </div>

    <p class="text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
```

- [ ] **Step 3: Register it and drop the oldest section**

In `tourVisuals.ts`:

- Remove the `CodexSignInTourVisual` import and its `"codex-device-sign-in"` entry.
- Add `import ChatEvalsTourVisual from "@/features/release-tour/components/visuals/ChatEvalsTourVisual.vue";` in alphabetical order.
- Add `"chat-evals": ChatEvalsTourVisual,` after `"canvas-collaboration"`.

Delete the old visual:

```bash
git rm frontend/src/features/release-tour/components/visuals/CodexSignInTourVisual.vue
```

In `releaseRegistry.ts`:

- In release `2026.21`, set `sectionOrder: ["node-ai-edit"]` and delete the whole `codex-device-sign-in` section object.
- In release `2026.22`, set `sectionOrder: ["agent-suite", "chat-evals", "concurrency-limit", "canvas-collaboration"]`, and insert this section right after the `agent-suite` section:

```ts
      {
        id: "chat-evals",
        title: "Create and run eval suites from Chat",
        publishedAt: new Date("2026-10-26T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Ask **Chat** for an eval suite in plain words, for example *\"make a prompt suite for my support prompt and compare gpt-4o with gpt-4.1-mini\"*. Chat writes the test cases with their expected answers. It asks which credential and models to use, or uses your only one. Then it saves the suite in **Evals**, runs it, and reports each model's pass count and the cases that failed.",
          },
          {
            type: "prose",
            markdown:
              "For an **agent suite**, Chat picks the agent and writes the run inputs itself. It can run the workflow and save those runs as the baseline, take the baseline from the agent's latest runs, or store the numbers you give it. The same works from an MCP client through `heym_chat`.",
          },
        ],
        tour: {
          description:
            "Describe the suite you want. Chat writes the test cases, picks the credential with you, and runs it.",
          useCases: [
            "Compare two models on a prompt without building the suite by hand",
            "Build an agent's baseline from fresh runs when it has none yet",
            "Re-run a suite from an MCP client and read what failed",
          ],
          tourVisual: "chat-evals",
          docTarget: {
            categoryId: "tabs",
            slug: "chat-tab",
            title: "Chat",
          },
        },
      },
```

- [ ] **Step 4: Run the frontend checks**

Run: `cd frontend && bun run test src/features/release-tour && bun run lint && bun run typecheck`
Expected: all pass. `frontend/e2e/support.ts` derives the seen id from the registry, so it needs no change.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/release-tour
git commit -m "feat(release-tour): announce eval suites from Chat"
```

---

### Task 13: Full verification

- [ ] **Step 1: Backend format, lint and the whole test suite**

Run from the repo root with the Prerequisites variables exported:

```bash
./check.sh > /tmp/claude-check.log 2>&1; echo "exit: $?" >> /tmp/claude-check.log; tail -40 /tmp/claude-check.log
```

Expected: `exit: 0`. If `ruff format` changed files, review the diff and commit it as `style: ruff format`.

- [ ] **Step 2: Frontend unit tests (CI runs them; check.sh does not)**

Run: `cd frontend && bun run test`
Expected: all pass

- [ ] **Step 3: Manual smoke in the real app (needs an LLM credential)**

Start `./run.sh`, open Chat, and send these three messages in order, checking each result:

1. "Make a prompt suite for 'Classify the ticket as billing, bug or other' with 5 test cases and compare two models."
   - Expect a question about credential and models (unless you have one LLM credential).
   - Then the suite saves, runs, and the reply shows per-model counts and a link to `/evals?suite=…`.
2. "Create an agent suite for <an agent with no runs>, run it 3 times and use those runs as the baseline."
   - Expect three executions in Execution History with the `agent_suite` trigger.
   - **Edit checks** shows "from a suite run".
3. Repeat message 1 through MCP `heym_chat` from an MCP client.
   - Expect the same result with an absolute link.
   - `tools/list` shows no eval tool.

Report what was and was not smoke-tested.

- [ ] **Step 4: Clean up**

```bash
docker rm -f heym-evals-pg
```
