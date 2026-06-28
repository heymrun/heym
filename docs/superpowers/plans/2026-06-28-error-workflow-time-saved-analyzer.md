# Error Workflow, Time Saved & Analyzer Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a workflow-level "on error, run workflow" setting, a manual "time saved" estimate surfaced in analytics, and upgrade the AI workflow analyzer with three explicit capabilities plus a Properties-panel "Run Analyzer" button.

**Architecture:** Two new nullable columns on `Workflow` (`error_workflow_id`, `minutes_saved_per_run`). A new backend service `error_workflow_runner.py` decides whether and how to run an external error workflow when a top-level run fails and the canvas has no local `errorHandler` node; it is invoked from the main execute path. Analytics gains a `time_saved_minutes` aggregate. The Properties panel (workflow-level, no node selected) gains the error-workflow selector, the time-saved input, and a Run Analyzer button. The analyzer system prompt is extended and fed three new context flags.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic (backend), Vue 3 `<script setup>` + TypeScript + Pinia (frontend), pytest (backend tests), Playwright (frontend E2E).

---

## File Structure

**Backend — create:**
- `backend/app/services/error_workflow_runner.py` — guard + context-builder + runner for the external error workflow.
- `backend/alembic/versions/<rev>_add_error_workflow_and_time_saved.py` — migration for the two new columns.
- `backend/tests/test_error_workflow_runner.py` — unit tests for the runner.
- `backend/tests/test_time_saved_analytics.py` — unit tests for time-saved aggregation.

**Backend — modify:**
- `backend/app/db/models.py` — add columns to `Workflow`.
- `backend/app/models/schemas.py` — `WorkflowUpdate`, `WorkflowResponse`, `AnalyticsStatsResponse`.
- `backend/app/api/workflows.py` — update endpoint (persist + validate new fields), execute path (invoke error-workflow runner).
- `backend/app/api/analytics.py` — compute `time_saved_minutes`.
- `backend/app/api/ai_assistant.py` — extend `WORKFLOW_ANALYZE_SYSTEM_PROMPT` + enrich analyzer payload.

**Frontend — modify:**
- `frontend/src/types/workflow.ts` — `Workflow` interface fields.
- `frontend/src/types/analytics.ts` — `AnalyticsStats.time_saved_minutes`.
- `frontend/src/services/api.ts` — `workflowApi.update` Pick union.
- `frontend/src/components/Panels/PropertiesPanel.vue` — selector, time-saved input, Run Analyzer button.
- `frontend/src/components/Analytics/AnalyticsDashboard.vue` — Time saved stat card.
- `frontend/src/stores/workflow.ts` — expose "analysis note empty" signal (Task 11).

**Docs — modify (via heym-documentation skill):**
- `frontend/src/docs/content/reference/features.md` and related analyzer/analytics docs.

---

## Task 1: Add `error_workflow_id` and `minutes_saved_per_run` columns to the Workflow model

**Files:**
- Modify: `backend/app/db/models.py:281` (after `auto_recover_runs`)

- [ ] **Step 1: Add the columns**

In `backend/app/db/models.py`, immediately after the `auto_recover_runs` column (line 281), add:

```python
    error_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    minutes_saved_per_run: Mapped[float | None] = mapped_column(Float, nullable=True)
```

(`Float` is already imported in this module; confirm `from sqlalchemy import ... Float` is present — it is used by `WorkflowAnalyticsSnapshot`.)

- [ ] **Step 2: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add error_workflow_id and minutes_saved_per_run to Workflow model"
```

---

## Task 2: Alembic migration for the two new columns

**Files:**
- Create: `backend/alembic/versions/<rev>_add_error_workflow_and_time_saved.py`

- [ ] **Step 1: Find the current head revision**

Run: `cd backend && uv run alembic heads`
Note the revision id printed (e.g. `9d1f2a3b4c5d`). Use it as `down_revision` below.

- [ ] **Step 2: Create the migration file**

Create `backend/alembic/versions/a1b2c3d4e5f6_add_error_workflow_and_time_saved.py` (pick any unused 12-char hex for the filename/`revision`):

```python
"""add error_workflow_id and minutes_saved_per_run to workflows

Revision ID: a1b2c3d4e5f6
Revises: <PASTE_CURRENT_HEAD_HERE>
Create Date: 2026-06-28

"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "<PASTE_CURRENT_HEAD_HERE>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("error_workflow_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "workflows",
        sa.Column("minutes_saved_per_run", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_workflows_error_workflow_id", "workflows", ["error_workflow_id"]
    )
    op.create_foreign_key(
        "fk_workflows_error_workflow_id",
        "workflows",
        "workflows",
        ["error_workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_workflows_error_workflow_id", "workflows", type_="foreignkey"
    )
    op.drop_index("ix_workflows_error_workflow_id", table_name="workflows")
    op.drop_column("workflows", "minutes_saved_per_run")
    op.drop_column("workflows", "error_workflow_id")
```

- [ ] **Step 3: Apply the migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: completes with no error; `alembic heads` now shows the new revision.

- [ ] **Step 4: Verify downgrade/upgrade round-trips**

Run: `cd backend && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: both complete cleanly.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/a1b2c3d4e5f6_add_error_workflow_and_time_saved.py
git commit -m "feat: migration for error_workflow_id and minutes_saved_per_run"
```

---

## Task 3: Add fields to schemas and persist them in the update endpoint

**Files:**
- Modify: `backend/app/models/schemas.py:189` (WorkflowUpdate), `:225` (WorkflowResponse)
- Modify: `backend/app/api/workflows.py:1141` (update endpoint)
- Test: `backend/tests/test_workflow_error_settings.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_error_settings.py`:

```python
import unittest
import uuid

from app.models.schemas import WorkflowUpdate


class TestWorkflowUpdateSchema(unittest.TestCase):
    def test_accepts_error_workflow_id_and_minutes_saved(self) -> None:
        wid = uuid.uuid4()
        update = WorkflowUpdate(error_workflow_id=wid, minutes_saved_per_run=12.5)
        self.assertEqual(update.error_workflow_id, wid)
        self.assertEqual(update.minutes_saved_per_run, 12.5)

    def test_fields_default_to_none(self) -> None:
        update = WorkflowUpdate()
        self.assertIsNone(update.error_workflow_id)
        self.assertIsNone(update.minutes_saved_per_run)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_error_settings.py -v`
Expected: FAIL — `WorkflowUpdate` has no `error_workflow_id`.

- [ ] **Step 3: Add fields to `WorkflowUpdate`**

In `backend/app/models/schemas.py`, after `auto_recover_runs: bool | None = None` (line 189):

```python
    error_workflow_id: uuid.UUID | None = None
    minutes_saved_per_run: float | None = None
```

- [ ] **Step 4: Add fields to `WorkflowResponse`**

In `backend/app/models/schemas.py`, after `auto_recover_runs: bool = True` (line 225):

```python
    error_workflow_id: uuid.UUID | None = None
    minutes_saved_per_run: float | None = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_error_settings.py -v`
Expected: PASS.

- [ ] **Step 6: Persist + validate in the update endpoint**

In `backend/app/api/workflows.py`, after the `auto_recover_runs` block (line 1141-1142), add:

```python
    if workflow_data.error_workflow_id is not None:
        # Empty UUID (all-zeros) clears the setting; a workflow cannot target itself.
        if workflow_data.error_workflow_id == uuid.UUID(int=0):
            workflow.error_workflow_id = None
        elif workflow_data.error_workflow_id == workflow_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A workflow cannot be its own error workflow",
            )
        else:
            target = await get_workflow_for_user(
                db, workflow_data.error_workflow_id, current_user.id
            )
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Error workflow not found or not accessible",
                )
            workflow.error_workflow_id = workflow_data.error_workflow_id
    if workflow_data.minutes_saved_per_run is not None:
        workflow.minutes_saved_per_run = (
            workflow_data.minutes_saved_per_run
            if workflow_data.minutes_saved_per_run > 0
            else None
        )
```

Note: clients clear the selection by sending the all-zeros UUID (`00000000-0000-0000-0000-000000000000`), matching the "None" option wired in Task 9.

- [ ] **Step 7: Run the broader workflow tests to confirm nothing broke**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_error_settings.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/workflows.py backend/tests/test_workflow_error_settings.py
git commit -m "feat: persist and validate error_workflow_id and minutes_saved_per_run"
```

---

## Task 4: Error-workflow runner — pure guard and context builder

**Files:**
- Create: `backend/app/services/error_workflow_runner.py`
- Test: `backend/tests/test_error_workflow_runner.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_error_workflow_runner.py`:

```python
import unittest
import uuid

from app.services.error_workflow_runner import (
    build_error_context,
    should_run_error_workflow,
)


def _wf(error_workflow_id=None, nodes=None):
    class _W:
        pass

    w = _W()
    w.id = uuid.uuid4()
    w.name = "My WF"
    w.error_workflow_id = error_workflow_id
    w.nodes = nodes or []
    return w


class TestShouldRunErrorWorkflow(unittest.TestCase):
    def test_runs_when_error_no_handler_and_target_set(self) -> None:
        wf = _wf(error_workflow_id=uuid.uuid4(), nodes=[{"type": "httpRequest"}])
        self.assertTrue(should_run_error_workflow(wf, "error"))

    def test_skips_when_status_not_error(self) -> None:
        wf = _wf(error_workflow_id=uuid.uuid4(), nodes=[{"type": "httpRequest"}])
        self.assertFalse(should_run_error_workflow(wf, "success"))

    def test_skips_when_no_error_workflow_id(self) -> None:
        wf = _wf(error_workflow_id=None, nodes=[{"type": "httpRequest"}])
        self.assertFalse(should_run_error_workflow(wf, "error"))

    def test_skips_when_local_errorHandler_node_present(self) -> None:
        wf = _wf(
            error_workflow_id=uuid.uuid4(),
            nodes=[{"type": "httpRequest"}, {"type": "errorHandler"}],
        )
        self.assertFalse(should_run_error_workflow(wf, "error"))


class TestBuildErrorContext(unittest.TestCase):
    def test_extracts_failed_node_from_results(self) -> None:
        wf = _wf()
        node_results = [
            {"node_label": "ok", "node_type": "textInput", "status": "success"},
            {
                "node_label": "callApi",
                "node_type": "httpRequest",
                "status": "error",
                "error": "boom",
            },
        ]
        ctx = build_error_context(wf, node_results, run_id="run-1")
        self.assertEqual(ctx["workflow_name"], "My WF")
        self.assertEqual(ctx["run_id"], "run-1")
        self.assertEqual(ctx["errorNode"], "callApi")
        self.assertEqual(ctx["errorNodeType"], "httpRequest")
        self.assertEqual(ctx["error"], "boom")
        self.assertIn("timestamp", ctx)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_error_workflow_runner.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the pure helpers**

Create `backend/app/services/error_workflow_runner.py`:

```python
"""Run an external "error workflow" when a top-level run fails.

A workflow may designate another workflow (``error_workflow_id``) to run when it
fails. This is suppressed when the canvas already has a local ``errorHandler``
node (the "Global Error Catcher"), which handles errors in-workflow.

The error workflow is executed directly via ``execute_workflow`` (not through the
HTTP execute path), so it never re-enters this hook — no recursion guard beyond
that is required.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _has_local_error_handler(nodes: list[dict[str, Any]] | None) -> bool:
    return any(
        isinstance(n, dict) and n.get("type") == "errorHandler" for n in (nodes or [])
    )


def should_run_error_workflow(workflow: Any, status: str) -> bool:
    """True when the failed run should trigger the configured error workflow."""
    if status != "error":
        return False
    if getattr(workflow, "error_workflow_id", None) is None:
        return False
    if _has_local_error_handler(getattr(workflow, "nodes", None)):
        return False
    return True


def build_error_context(
    workflow: Any, node_results: list[dict[str, Any]], run_id: str | None
) -> dict[str, Any]:
    """Build the payload passed to the error workflow as input ``body``."""
    failed = next(
        (
            r
            for r in (node_results or [])
            if isinstance(r, dict) and r.get("status") == "error"
        ),
        None,
    )
    return {
        "workflow_id": str(getattr(workflow, "id", "")),
        "workflow_name": getattr(workflow, "name", ""),
        "run_id": str(run_id) if run_id is not None else None,
        "error": (failed or {}).get("error"),
        "errorNode": (failed or {}).get("node_label"),
        "errorNodeType": (failed or {}).get("node_type"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_error_workflow_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/error_workflow_runner.py backend/tests/test_error_workflow_runner.py
git commit -m "feat: error-workflow runner guard and context builder"
```

---

## Task 5: Error-workflow runner — load target and execute

**Files:**
- Modify: `backend/app/services/error_workflow_runner.py`
- Test: `backend/tests/test_error_workflow_runner.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_error_workflow_runner.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestRunErrorWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_guard_false(self) -> None:
        wf = _wf(error_workflow_id=None, nodes=[])
        db = AsyncMock()
        with patch(
            "app.services.error_workflow_runner.execute_workflow"
        ) as exec_mock:
            ran = await maybe_run_error_workflow(
                db, wf, status="success", node_results=[], run_id="r", actor_user_id=uuid.uuid4()
            )
        self.assertFalse(ran)
        exec_mock.assert_not_called()

    async def test_runs_target_when_guard_true(self) -> None:
        target_id = uuid.uuid4()
        wf = _wf(error_workflow_id=target_id, nodes=[{"type": "httpRequest"}])

        target = MagicMock()
        target.id = target_id
        target.nodes = [{"id": "n1", "type": "output", "data": {"label": "out"}}]
        target.edges = []
        target.owner_id = uuid.uuid4()

        db = AsyncMock()
        with patch(
            "app.services.error_workflow_runner._load_workflow", new=AsyncMock(return_value=target)
        ), patch(
            "app.services.error_workflow_runner.collect_referenced_workflows",
            new=AsyncMock(return_value={}),
        ), patch(
            "app.services.error_workflow_runner.get_credentials_context",
            new=AsyncMock(return_value={}),
        ), patch(
            "app.services.error_workflow_runner.get_global_variables_context",
            new=AsyncMock(return_value={}),
        ), patch(
            "app.services.error_workflow_runner.asyncio.to_thread", new=AsyncMock()
        ) as to_thread_mock:
            ran = await maybe_run_error_workflow(
                db, wf, status="error",
                node_results=[{"status": "error", "error": "boom", "node_label": "x", "node_type": "httpRequest"}],
                run_id="r", actor_user_id=uuid.uuid4(),
            )

        self.assertTrue(ran)
        to_thread_mock.assert_awaited()

    async def test_swallows_target_failure(self) -> None:
        target_id = uuid.uuid4()
        wf = _wf(error_workflow_id=target_id, nodes=[{"type": "httpRequest"}])
        db = AsyncMock()
        with patch(
            "app.services.error_workflow_runner._load_workflow",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            # Must not raise even though loading the target failed.
            ran = await maybe_run_error_workflow(
                db, wf, status="error",
                node_results=[{"status": "error"}],
                run_id="r", actor_user_id=uuid.uuid4(),
            )
        self.assertFalse(ran)
```

Also add to the imports at the top of the test file:

```python
from app.services.error_workflow_runner import maybe_run_error_workflow
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_error_workflow_runner.py -v`
Expected: FAIL — `maybe_run_error_workflow` and `_load_workflow` are undefined.

- [ ] **Step 3: Implement the runner**

Append to `backend/app/services/error_workflow_runner.py` (and add the imports at the top of the file):

```python
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.workflows import collect_referenced_workflows
from app.db.models import ExecutionHistory, Workflow
from app.services.workflow_executor import execute_workflow
from app.utils.context_helpers import (
    get_credentials_context,
    get_global_variables_context,
)
```

> If `get_credentials_context` / `get_global_variables_context` are not in `app.utils.context_helpers`, locate them with
> `grep -rn "def get_credentials_context\|def get_global_variables_context" backend/app` and import from the module that defines them. They are the same helpers used in `workflows.py`'s execute path.

```python
async def _load_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow | None:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    return result.scalar_one_or_none()


async def maybe_run_error_workflow(
    db: AsyncSession,
    workflow: Any,
    *,
    status: str,
    node_results: list[dict[str, Any]],
    run_id: str | None,
    actor_user_id: uuid.UUID,
) -> bool:
    """Run the configured error workflow if the guard passes. Never raises."""
    try:
        if not should_run_error_workflow(workflow, status):
            return False

        target = await _load_workflow(db, workflow.error_workflow_id)
        if target is None:
            return False

        error_context = build_error_context(workflow, node_results, run_id)
        enriched_inputs = {"headers": {}, "query": {}, "body": error_context}

        workflow_cache = await collect_referenced_workflows(
            db, target.nodes, actor_user_id=actor_user_id
        )
        credentials_context = await get_credentials_context(db, actor_user_id)
        global_variables_context = await get_global_variables_context(db, actor_user_id)

        result = await asyncio.to_thread(
            execute_workflow,
            workflow_id=target.id,
            nodes=target.nodes,
            edges=target.edges,
            inputs=enriched_inputs,
            workflow_cache=workflow_cache,
            test_run=False,
            credentials_context=credentials_context,
            global_variables_context=global_variables_context,
            trace_user_id=actor_user_id,
            actor_user_id=actor_user_id,
        )

        history = ExecutionHistory(
            workflow_id=target.id,
            inputs=enriched_inputs,
            outputs=result.outputs,
            node_results=result.node_results,
            status=result.status,
            execution_time_ms=result.execution_time_ms,
            trigger_source="ERROR_WORKFLOW",
        )
        db.add(history)
        await db.flush()
        return True
    except Exception:  # noqa: BLE001 — error workflow must never mask the original failure
        logger.exception("Error workflow execution failed for %s", getattr(workflow, "id", "?"))
        return False
```

> If `collect_referenced_workflows` imported from `app.api.workflows` causes a circular import at module load, import it lazily inside `maybe_run_error_workflow` instead (move the `from app.api.workflows import collect_referenced_workflows` line into the function body).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_error_workflow_runner.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/error_workflow_runner.py backend/tests/test_error_workflow_runner.py
git commit -m "feat: load and execute the configured error workflow"
```

---

## Task 6: Invoke the error-workflow runner from the execute path

**Files:**
- Modify: `backend/app/api/workflows.py` (after the non-test history entry is created in the execute path, around line 2462-2470)

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "trigger_source=trigger_source,\n        )\n        db.add(history_entry)" backend/app/api/workflows.py` — practically, find the block at ~2451-2470 where, for `not test_run`, `history_entry = ExecutionHistory(...)` is created with `status=execution_result.status` and `db.add(history_entry)` then `upsert_workflow_analytics_snapshot(...)`.

- [ ] **Step 2: Add the runner call after that snapshot upsert**

Immediately after the `await upsert_workflow_analytics_snapshot(...)` call that follows `db.add(history_entry)` (the non-test, non-pending branch ending near line 2470), insert:

```python
        if execution_result.status == "error":
            from app.services.error_workflow_runner import maybe_run_error_workflow

            await db.flush()  # ensure history_entry.id is available
            await maybe_run_error_workflow(
                db,
                workflow,
                status=execution_result.status,
                node_results=execution_result.node_results,
                run_id=str(history_entry.id) if history_entry else None,
                actor_user_id=credentials_owner_id,
            )
```

(The import is local to avoid any circular-import risk between `workflows.py` and `error_workflow_runner.py`.)

- [ ] **Step 3: Verify the backend imports cleanly**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.api.workflows"`
Expected: no ImportError.

- [ ] **Step 4: Run the runner tests again (regression)**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_error_workflow_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py
git commit -m "feat: trigger error workflow on failed top-level runs"
```

---

## Task 7: Compute `time_saved_minutes` in analytics

**Files:**
- Modify: `backend/app/models/schemas.py:1150` (AnalyticsStatsResponse), `backend/app/api/analytics.py` (`_empty_analytics_stats`, `compute_analytics_stats`, `_compute_stats_from_history`)
- Test: `backend/tests/test_time_saved_analytics.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_time_saved_analytics.py`:

```python
import unittest
import uuid

from app.api.analytics import compute_time_saved_minutes


class TestComputeTimeSaved(unittest.TestCase):
    def test_sums_rate_times_success_count(self) -> None:
        wid_a = uuid.uuid4()
        wid_b = uuid.uuid4()
        success_by_workflow = {wid_a: 10, wid_b: 4}
        rate_by_workflow = {wid_a: 3.0, wid_b: 5.0}
        # 10*3 + 4*5 = 50
        self.assertEqual(
            compute_time_saved_minutes(success_by_workflow, rate_by_workflow), 50.0
        )

    def test_missing_rate_counts_zero(self) -> None:
        wid = uuid.uuid4()
        self.assertEqual(
            compute_time_saved_minutes({wid: 7}, {}), 0.0
        )

    def test_none_workflow_id_ignored(self) -> None:
        wid = uuid.uuid4()
        self.assertEqual(
            compute_time_saved_minutes({wid: 2, None: 99}, {wid: 4.0}), 8.0
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_time_saved_analytics.py -v`
Expected: FAIL — `compute_time_saved_minutes` undefined.

- [ ] **Step 3: Add `time_saved_minutes` to the response schema**

In `backend/app/models/schemas.py`, inside `AnalyticsStatsResponse` (after `avg_latency_24h_ms: float`, line 1163):

```python
    time_saved_minutes: float = 0.0
```

- [ ] **Step 4: Add the pure helper and wire it into `compute_analytics_stats`**

In `backend/app/api/analytics.py`, add a module-level helper (place it near `calculate_percentile`):

```python
def compute_time_saved_minutes(
    success_by_workflow: dict[uuid.UUID | None, int],
    rate_by_workflow: dict[uuid.UUID, float],
) -> float:
    """Σ (minutes_saved_per_run × successful runs) over workflows with a known rate."""
    total = 0.0
    for wid, success_count in success_by_workflow.items():
        if wid is None:
            continue
        rate = rate_by_workflow.get(wid)
        if rate:
            total += rate * success_count
    return total
```

Then, inside `compute_analytics_stats` (after `all_rows` is fetched, before the final `return AnalyticsStatsResponse(...)`), build the per-workflow success map and fetch rates:

```python
    success_by_workflow: dict[uuid.UUID | None, int] = {}
    for row in all_rows:
        success_by_workflow[row.workflow_id] = (
            success_by_workflow.get(row.workflow_id, 0) + row.success_count
        )

    rate_rows = await db.execute(
        select(Workflow.id, Workflow.minutes_saved_per_run).where(
            Workflow.id.in_([wid for wid in success_by_workflow if wid is not None])
        )
    ) if any(wid is not None for wid in success_by_workflow) else None
    rate_by_workflow: dict[uuid.UUID, float] = {}
    if rate_rows is not None:
        for rid, rate in rate_rows.all():
            if rate:
                rate_by_workflow[rid] = float(rate)

    time_saved_minutes = compute_time_saved_minutes(success_by_workflow, rate_by_workflow)
```

Ensure `Workflow` is imported in `analytics.py` (add `from app.db.models import WorkflowAnalyticsSnapshot, Workflow` if `Workflow` is not already imported — verify with `grep -n "from app.db.models import" backend/app/api/analytics.py`).

Add `time_saved_minutes=time_saved_minutes,` to the `return AnalyticsStatsResponse(...)` in `compute_analytics_stats`.

- [ ] **Step 5: Set `time_saved_minutes=0.0` in the other return sites**

In `_empty_analytics_stats` and `_compute_stats_from_history`, add `time_saved_minutes=0.0,` to their `AnalyticsStatsResponse(...)` constructions (the history-fallback path has no snapshot rows to derive a rate map; 0.0 is acceptable per spec).

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_time_saved_analytics.py -v`
Expected: PASS.

- [ ] **Step 7: Verify analytics module imports**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.api.analytics"`
Expected: no error.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/analytics.py backend/tests/test_time_saved_analytics.py
git commit -m "feat: compute time_saved_minutes in analytics stats"
```

---

## Task 8: Extend the analyzer system prompt + payload (3 capabilities)

**Files:**
- Modify: `backend/app/api/ai_assistant.py:153` (WORKFLOW_ANALYZE_SYSTEM_PROMPT), `:3527` (analyze_workflow_stream payload)
- Test: `backend/tests/test_workflow_analyze_prompt.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_analyze_prompt.py`:

```python
import unittest

from app.api.ai_assistant import WORKFLOW_ANALYZE_SYSTEM_PROMPT


class TestAnalyzePrompt(unittest.TestCase):
    def test_mentions_three_capabilities(self) -> None:
        p = WORKFLOW_ANALYZE_SYSTEM_PROMPT.lower()
        self.assertIn("error handling", p)
        self.assertIn("error workflow", p)
        self.assertIn("time saved", p)
        self.assertIn("network", p)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analyze_prompt.py -v`
Expected: FAIL — prompt lacks the new terms.

- [ ] **Step 3: Extend the prompt**

In `backend/app/api/ai_assistant.py`, replace the `## Improvement areas` paragraph in `WORKFLOW_ANALYZE_SYSTEM_PROMPT` (line 157-158) with a version that adds the three explicit capabilities. Insert these bullet instructions into the "Improvement areas" section:

```python
WORKFLOW_ANALYZE_SYSTEM_PROMPT = """You analyze an automation workflow and produce a clear Markdown report.

Given the workflow's nodes and edges, write Markdown with these sections, in this exact order:

## Improvement areas
A bulleted list of concrete, actionable suggestions (reliability, error handling, missing validation, cost, clarity). Whenever the workflow handles credentials, user input, external requests, data exposure, injection-prone steps, or anything else security-relevant, include a clear **security** angle here (risks and how to mitigate them). Always cover these three checks explicitly:
1. **Error handling** — Inspect the provided `analysisContext`. If `hasErrorHandler` is false AND `errorWorkflowConfigured` is false, call out that this workflow has no error handling at all (no errorHandler node on the canvas and no error workflow configured) and recommend adding an errorHandler node and/or configuring an "on error, run workflow".
2. **Time saved** — If `minutesSavedPerRun` is null or zero, recommend setting an estimated "time saved per run" so the analytics time-saved metric can populate. If it is set, acknowledge the configured value.
3. **Network nodes** — For any node that performs network I/O (e.g. `httpRequest` and integration/API nodes such as slack, drive, notion, etc.), recommend node-specific error handling (enable retry and/or onError "continue on error") on those specific nodes by label.

If the workflow already looks solid, say so and suggest small refinements.

## Purpose
One or two sentences on what this workflow is for.

## What it does
A numbered, step-by-step walk through the nodes in execution order, in plain language.

Output ONLY Markdown. Do not include JSON, code fences around the whole document, or tool calls. Be concise and specific to THIS workflow."""
```

- [ ] **Step 4: Feed `analysisContext` into the prompt**

In `analyze_workflow_stream` (around line 3528-3531), after the workflow JSON is appended, add an `analysisContext` block derived from the workflow payload:

```python
    if request.current_workflow:
        wf_summary = json.dumps(request.current_workflow, ensure_ascii=False)
        system_prompt += f"\n\nWorkflow:\n```json\n{wf_summary}\n```"
        nodes = request.current_workflow.get("nodes") or []
        has_error_handler = any(
            isinstance(n, dict) and n.get("type") == "errorHandler" for n in nodes
        )
        analysis_context = {
            "hasErrorHandler": has_error_handler,
            "errorWorkflowConfigured": bool(
                request.current_workflow.get("error_workflow_id")
            ),
            "minutesSavedPerRun": request.current_workflow.get("minutes_saved_per_run"),
        }
        system_prompt += (
            "\n\nanalysisContext:\n```json\n"
            + json.dumps(analysis_context, ensure_ascii=False)
            + "\n```"
        )
```

> Note: the frontend already sends the whole workflow payload as `currentWorkflow`. Confirm `error_workflow_id` / `minutes_saved_per_run` are included in the payload the canvas sends (Task 10 adds them to the `Workflow` type; the analyze call in `AnalysisPanel.vue` passes `props.currentWorkflow`, which is built from the store's `currentWorkflow`). If those keys are stripped before sending, add them to the `AnalysisWorkflowPayload` mapping in `AnalysisPanel.vue`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analyze_prompt.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_workflow_analyze_prompt.py
git commit -m "feat: analyzer reports error coverage, time saved, and network-node error handling"
```

---

## Task 9: Frontend types + api for new workflow fields

**Files:**
- Modify: `frontend/src/types/workflow.ts:35`, `frontend/src/types/analytics.ts:13`, `frontend/src/services/api.ts:514`

- [ ] **Step 1: Add fields to the `Workflow` interface**

In `frontend/src/types/workflow.ts`, after `auto_recover_runs: boolean;` (line 35):

```typescript
  error_workflow_id: string | null;
  minutes_saved_per_run: number | null;
```

- [ ] **Step 2: Add `time_saved_minutes` to `AnalyticsStats`**

In `frontend/src/types/analytics.ts`, inside `AnalyticsStats` after `avg_latency_24h_ms: number;` (line 13):

```typescript
  time_saved_minutes: number;
```

- [ ] **Step 3: Allow the new fields in `workflowApi.update`**

In `frontend/src/services/api.ts`, add to the `Pick<Workflow, ...>` union in `update` (after `"auto_recover_runs"`, line 514):

```typescript
        | "error_workflow_id"
        | "minutes_saved_per_run"
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS (no new errors). If `Workflow` is constructed anywhere as an object literal that now lacks the two required fields, make them required only where the API supplies them; the API responses include them, so existing usages reading `Workflow` are unaffected. If typecheck flags a literal, set the missing fields to `null` there.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/types/analytics.ts frontend/src/services/api.ts
git commit -m "feat: frontend types for error workflow and time saved"
```

---

## Task 10: Properties panel — error workflow selector + time-saved input

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue` (script around line 321-335; template around line 7862-7893)

- [ ] **Step 1: Add state + load the workflow list in the script**

In `PropertiesPanel.vue`, near `autoRecoverRuns`/`onToggleAutoRecover` (line 321-335), add:

```typescript
import { onMounted, ref } from "vue"; // merge into existing vue import if already importing these
import type { WorkflowListItem } from "@/types/workflow"; // merge with existing type imports

const otherWorkflows = ref<WorkflowListItem[]>([]);

async function loadOtherWorkflows(): Promise<void> {
  try {
    const all = await workflowApi.list();
    const currentId = workflowStore.currentWorkflow?.id;
    otherWorkflows.value = all.filter((w) => w.id !== currentId);
  } catch {
    otherWorkflows.value = [];
  }
}

onMounted(() => {
  void loadOtherWorkflows();
});

const errorWorkflowId = computed(
  () => workflowStore.currentWorkflow?.error_workflow_id ?? "",
);

const EMPTY_UUID = "00000000-0000-0000-0000-000000000000";

async function onChangeErrorWorkflow(value: string): Promise<void> {
  const wf = workflowStore.currentWorkflow;
  if (!wf || !isWorkflowOwner.value) return;
  const previous = wf.error_workflow_id;
  const next = value === "" ? null : value;
  wf.error_workflow_id = next;
  try {
    await workflowApi.update(wf.id, {
      error_workflow_id: next === null ? EMPTY_UUID : next,
    });
  } catch {
    wf.error_workflow_id = previous;
  }
}

const minutesSavedPerRun = computed(
  () => workflowStore.currentWorkflow?.minutes_saved_per_run ?? null,
);

async function onChangeMinutesSaved(raw: string): Promise<void> {
  const wf = workflowStore.currentWorkflow;
  if (!wf || !isWorkflowOwner.value) return;
  const parsed = raw === "" ? null : Number(raw);
  const next = parsed !== null && Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  const previous = wf.minutes_saved_per_run;
  wf.minutes_saved_per_run = next;
  try {
    await workflowApi.update(wf.id, { minutes_saved_per_run: next ?? 0 });
  } catch {
    wf.minutes_saved_per_run = previous;
  }
}
```

> `Number.isFinite`, `computed`, `workflowApi` are already in scope in this file. Reuse the existing `computed` import; do not duplicate imports — merge the new symbols into the existing `import { ... } from "vue"` and type-import lines.

- [ ] **Step 2: Add the controls to the template, above "Auto-recover runs"**

In the workflow-level block (line 7866, the `<div class="border-t border-border/40 pt-4">` that wraps Auto-recover runs), add a sibling block **before** it (still inside the `v-if="workflowStore.currentWorkflow"` container at line 7862):

```html
            <div class="pb-4">
              <div class="flex items-center gap-2 mb-2">
                <AlertTriangle class="w-4 h-4 text-muted-foreground shrink-0" />
                <span class="text-sm font-medium">On error, run workflow</span>
              </div>
              <select
                class="w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
                :value="errorWorkflowId"
                :disabled="!isWorkflowOwner"
                @change="onChangeErrorWorkflow(($event.target as HTMLSelectElement).value)"
              >
                <option value="">
                  None
                </option>
                <option
                  v-for="w in otherWorkflows"
                  :key="w.id"
                  :value="w.id"
                >
                  {{ w.name }}
                </option>
              </select>
              <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
                Runs the selected workflow if this one fails — unless the canvas
                already has an Error Handler node.
              </p>
            </div>

            <div class="border-t border-border/40 pt-4 pb-4">
              <div class="flex items-center gap-2 mb-2">
                <Clock class="w-4 h-4 text-muted-foreground shrink-0" />
                <span class="text-sm font-medium">Time saved per run (min)</span>
              </div>
              <input
                type="number"
                min="0"
                step="1"
                class="w-full text-sm rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50"
                :value="minutesSavedPerRun ?? ''"
                :disabled="!isWorkflowOwner"
                placeholder="e.g. 15"
                @change="onChangeMinutesSaved(($event.target as HTMLInputElement).value)"
              >
              <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
                Estimated minutes this automation saves per successful run.
                Surfaced as total Time Saved in Analytics.
              </p>
            </div>
```

- [ ] **Step 3: Ensure icons are imported**

Confirm `AlertTriangle` and `Clock` are imported from `lucide-vue-next` in `PropertiesPanel.vue`. If not, add them to the existing `lucide-vue-next` import. (`RotateCcw` is already imported there.)

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: error workflow selector and time-saved input in properties panel"
```

---

## Task 11: Properties panel — Run Analyzer button

**Files:**
- Modify: `frontend/src/stores/workflow.ts` (expose `analysisNoteEmpty`), `frontend/src/components/Panels/PropertiesPanel.vue` (button)

- [ ] **Step 1: Add an `analysisNoteEmpty` signal to the store**

In `frontend/src/stores/workflow.ts`, near `analysisPanelOpen` (line 69), add a ref and load it when the workflow loads:

```typescript
  const analysisNoteEmpty = ref(true);
```

Find where `currentWorkflow` is assigned after fetching a workflow (search for `currentWorkflow.value =`). After it is set with a saved (non-empty `id`) workflow, fetch the note presence:

```typescript
  async function refreshAnalysisNoteEmpty(): Promise<void> {
    const id = currentWorkflow.value?.id;
    if (!id) {
      analysisNoteEmpty.value = true;
      return;
    }
    try {
      const note = await workflowApi.getAnalysisNote(id);
      analysisNoteEmpty.value = note.content.trim() === "";
    } catch {
      analysisNoteEmpty.value = true;
    }
  }
```

Call `void refreshAnalysisNoteEmpty();` wherever the workflow is loaded into `currentWorkflow`, and add both `analysisNoteEmpty` and `refreshAnalysisNoteEmpty` to the store's returned object. Ensure `workflowApi` is imported in the store (it already imports from `@/services/api` for other calls — verify with `grep -n "workflowApi" frontend/src/stores/workflow.ts`; if absent, add `import { workflowApi } from "@/services/api";`).

- [ ] **Step 2: Add the Run Analyzer button computed + handler in PropertiesPanel**

In `PropertiesPanel.vue` script:

```typescript
const showRunAnalyzer = computed(
  () =>
    (workflowStore.currentWorkflow?.nodes?.length ?? 0) > 0 &&
    workflowStore.analysisNoteEmpty,
);

function openAnalyzer(): void {
  workflowStore.analysisPanelOpen = true;
}
```

- [ ] **Step 3: Add the button to the template**

Inside the `v-if="workflowStore.currentWorkflow"` block (line 7862), above the "On error, run workflow" block from Task 10, add:

```html
            <div
              v-if="showRunAnalyzer"
              class="pb-4"
            >
              <button
                type="button"
                class="w-full inline-flex items-center justify-center gap-2 text-sm font-medium rounded-md px-3 py-2 bg-primary text-primary-foreground hover:opacity-90"
                @click="openAnalyzer"
              >
                <Sparkles class="w-4 h-4" />
                Run Analyzer
              </button>
              <p class="text-xs text-muted-foreground mt-2 leading-relaxed">
                This workflow has no analysis yet. Open the analyzer to generate
                a report.
              </p>
            </div>
```

Confirm `Sparkles` is imported from `lucide-vue-next` in this file; add it if missing.

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/workflow.ts frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: run analyzer button when canvas non-empty and analysis empty"
```

---

## Task 12: Analytics dashboard — Time saved stat card

**Files:**
- Modify: `frontend/src/components/Analytics/AnalyticsDashboard.vue` (grid around line 731-799)

- [ ] **Step 1: Add a `formatTimeSaved` helper**

In the `AnalyticsDashboard.vue` script (near `formatLatency`/`formatNumber`), add:

```typescript
function formatTimeSaved(minutes: number): string {
  if (!minutes || minutes <= 0) return "0m";
  const total = Math.round(minutes);
  const hrs = Math.floor(total / 60);
  const mins = total % 60;
  if (hrs > 0) return `${hrs}h ${mins}m`;
  return `${mins}m`;
}
```

- [ ] **Step 2: Add a fifth stat card**

After the "Avg Latency" `<Card>` (closes at line 798), inside the same `<div class="grid ...">`, add:

```html
        <Card class="p-4">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm text-muted-foreground">
                Time Saved
              </p>
              <p class="text-2xl font-bold">
                {{ formatTimeSaved(stats.time_saved_minutes) }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Based on per-workflow estimates
              </p>
            </div>
            <Clock class="h-8 w-8 text-blue-500" />
          </div>
        </Card>
```

Import `Clock` from `lucide-vue-next` in this file if not already imported.

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Analytics/AnalyticsDashboard.vue
git commit -m "feat: time saved stat card on analytics dashboard"
```

---

## Task 13: Documentation

**Files:**
- Modify: `frontend/src/docs/content/reference/features.md` and related analyzer/analytics docs (via the heym-documentation skill).

- [ ] **Step 1: Invoke the documentation skill**

Use the `heym-documentation` skill. Document:
- The workflow-level **On error, run workflow** setting (what triggers it, the `errorHandler`-node suppression rule).
- The **Time saved per run** estimate and the Analytics **Time Saved** card (how it is computed: minutes × successful runs).
- The analyzer's three explicit checks (error coverage, time saved, network-node error handling) and the **Run Analyzer** button in Properties.

Ensure `frontend/src/docs/content/reference/features.md` (the all-features reference) is updated as the user requested.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/docs
git commit -m "docs: error workflow, time saved, and analyzer upgrades"
```

---

## Task 14: Full check + E2E

- [ ] **Step 1: Run the full check suite**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: ruff format clean, backend tests + lint pass, frontend lint + typecheck pass. Commit any formatting-only diffs.

- [ ] **Step 2: (When practical) Add/extend Playwright E2E**

Add a spec under `frontend/e2e/` covering: the error-workflow selector and time-saved input persist for the owner, and the Run Analyzer button appears only when the canvas is non-empty and the analysis note is empty (and opens the Analysis panel). Run with `./run_e2e.sh`.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: formatting and E2E for error workflow + time saved + analyzer"
```

---

## Self-Review Notes

- **Spec coverage:** data model (T1-T3) ✓; error-workflow execution + errorHandler suppression + recursion avoidance (T4-T6) ✓; properties selector + time-saved input + Run Analyzer button opens panel only (T10-T11) ✓; time-saved analytics top card only (T7, T12) ✓; analyzer 3 capabilities (T8) ✓; docs incl. features.md (T13) ✓; tests (T3-T8, T14) ✓.
- **Recursion guard:** the error workflow runs via `execute_workflow` directly (not the HTTP execute hook), so it cannot re-enter `maybe_run_error_workflow`; documented in the module docstring.
- **Naming consistency:** `maybe_run_error_workflow`, `should_run_error_workflow`, `build_error_context`, `compute_time_saved_minutes`, `error_workflow_id`, `minutes_saved_per_run`, `time_saved_minutes`, `analysisNoteEmpty`, `showRunAnalyzer` used consistently across tasks.
- **Clear-selection convention:** the all-zeros UUID clears `error_workflow_id` (Task 3 endpoint ↔ Task 10 `EMPTY_UUID`).
