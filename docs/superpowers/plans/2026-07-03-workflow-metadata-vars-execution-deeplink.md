# Workflow Metadata Variables + Execution Deep-Link Bring-to-Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five workflow-metadata expression variables (`$workflowName`, `$workflowDescription`, `$workflowUrl`, `$workflowPath`, `$executionId`, the last runtime-only) and a navigable `/workflows/:id/:executionId` route that brings a past execution onto the canvas.

**Architecture:** Two independent features. Feature A injects the five variables into the executor's expression context (with parity in the expression-evaluate dialog service), sourcing name/description via the executor's existing lazy DB-fetch pattern and deriving url/path from `workflow_id` + base URL; `$executionId` is a per-run uuid. Feature B extends the editor route with an optional execution segment and reuses the existing `loadHistoryInputs` "Bring to Canvas" path.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy (backend); Vue 3 + TypeScript + Pinia + Vue Router (frontend); pytest (backend tests), Playwright (frontend E2E). No frontend unit-test harness — verify frontend via `bun run typecheck` + `bun run lint` and Playwright E2E.

---

## File Structure

**Backend (Feature A):**
- `backend/app/services/workflow_executor.py` — add ctor params + `_get_workflow_metadata()` + `_build_workflow_url()`, self-generate `execution_id`, inject 5 vars in `_build_context`.
- `backend/app/services/expression_evaluator.py` — accept + forward workflow metadata/base to the preview executor.
- `backend/app/api/expressions.py` — pass workflow id/name/description + base URL into the service.
- `backend/app/services/workflow_dsl_prompt.py` — document the 5 vars + reserved names.
- `backend/tests/test_expression_evaluator_service.py` — parity/format tests.
- `backend/tests/test_workflow_metadata_variables.py` (new) — executor context tests.

**Frontend (Feature A metadata + Feature B):**
- `frontend/src/types/expression.ts` — `WORKFLOW_BUILTINS` completion list.
- `frontend/src/composables/useExpressionCompletion.ts` — surface `WORKFLOW_BUILTINS`.
- `frontend/src/router/index.ts` — optional `:executionId` segment.
- `frontend/src/views/EditorView.vue` — deep-link fetch + `loadHistoryInputs`.
- `frontend/e2e/` — Playwright spec for the deep link.

**Docs:**
- `frontend/src/docs/content/reference/*` via the `heym-documentation` skill.

---

## Task 1: Executor system variables (Feature A core)

**Files:**
- Modify: `backend/app/services/workflow_executor.py` (ctor `__init__` at ~1709; `_build_context` at ~5444; add helpers near `_get_workflow_name_for_log` at ~2189; `execute()` method)
- Test: `backend/tests/test_workflow_metadata_variables.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_metadata_variables.py`:

```python
import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


class WorkflowMetadataVariablesTest(unittest.TestCase):
    def _executor(self, **kwargs) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[], **kwargs)

    def test_workflow_path_and_url_derived_from_id_and_base(self) -> None:
        wid = uuid.uuid4()
        executor = self._executor(
            workflow_id=wid,
            workflow_name="Daily Report",
            workflow_description="Sends a report",
            public_base_url="https://app.test/",
        )
        ctx = executor._build_context({})
        self.assertEqual(str(ctx["workflowName"]), "Daily Report")
        self.assertEqual(str(ctx["workflowDescription"]), "Sends a report")
        self.assertEqual(str(ctx["workflowPath"]), f"/workflows/{wid}")
        self.assertEqual(str(ctx["workflowUrl"]), f"https://app.test/workflows/{wid}")

    def test_empty_when_no_workflow_id(self) -> None:
        executor = self._executor(workflow_id=None)
        ctx = executor._build_context({})
        self.assertEqual(str(ctx["workflowPath"]), "")
        self.assertEqual(str(ctx["workflowUrl"]), "")

    def test_execution_id_empty_until_run_then_stable(self) -> None:
        executor = self._executor(workflow_id=uuid.uuid4())
        ctx_before = executor._build_context({})
        self.assertEqual(str(ctx_before["executionId"]), "")
        executor.execution_id = "abc123"
        ctx_after = executor._build_context({})
        self.assertEqual(str(ctx_after["executionId"]), "abc123")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_metadata_variables.py -v`
Expected: FAIL — `KeyError: 'workflowName'` (variables not injected yet).

- [ ] **Step 3: Add constructor params and metadata state**

In `WorkflowExecutor.__init__` (signature ends at ~1729), add three params just before `timeout_seconds`:

```python
        public_base_url: str = "",
        return_on_chart_output: bool = False,
        timeout_seconds: float | None = None,
        workflow_name: str = "",
        workflow_description: str = "",
        execution_id: str = "",
    ) -> None:
```

Then, near the other `self.workflow_id = workflow_id` assignment (~1748), add:

```python
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.workflow_description = workflow_description
        self.execution_id = execution_id
```

- [ ] **Step 4: Add metadata + URL helpers**

Immediately after `_get_workflow_name_for_log` (ends ~2203), add:

```python
    def _get_workflow_metadata(self) -> tuple[str, str]:
        """Return (name, description). Prefer explicitly supplied values; otherwise
        lazily fetch once from the DB by workflow_id (mirrors _get_workflow_name_for_log)."""
        if self.workflow_name or self.workflow_description:
            return self.workflow_name, self.workflow_description
        if not self.workflow_id:
            return "", ""
        if hasattr(self, "_workflow_metadata_cache"):
            return self._workflow_metadata_cache
        name, description = "", ""
        try:
            from app.db.models import Workflow
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                w = db.query(Workflow).filter(Workflow.id == self.workflow_id).first()
                if w is not None:
                    name = w.name or ""
                    description = w.description or ""
        except Exception:
            pass
        self._workflow_metadata_cache = (name, description)
        return self._workflow_metadata_cache

    def _build_workflow_url(self, workflow_path: str) -> str:
        if not workflow_path:
            return ""
        base = (self._base_url or "").rstrip("/")
        if not base:
            from app.config import settings

            base = (settings.frontend_url or "").rstrip("/")
        if not base:
            return ""
        return f"{base}{workflow_path}"
```

- [ ] **Step 5: Self-generate execution_id at run start**

Find the `execute(` method (the public entry called as `executor.execute(workflow_id, inputs)`). At the very start of its body, add:

```python
        if not self.execution_id:
            self.execution_id = uuid.uuid4().hex
```

- [ ] **Step 6: Inject the five variables in `_build_context`**

In `_build_context` (~5444), right after the `combined["false"] = False` line, add:

```python
        workflow_name, workflow_description = self._get_workflow_metadata()
        workflow_path = f"/workflows/{self.workflow_id}" if self.workflow_id else ""
        combined["workflowName"] = DotStr(workflow_name)
        combined["workflowDescription"] = DotStr(workflow_description)
        combined["workflowPath"] = DotStr(workflow_path)
        combined["workflowUrl"] = DotStr(self._build_workflow_url(workflow_path))
        combined["executionId"] = DotStr(self.execution_id or "")
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_metadata_variables.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Thread name/description through the wrapper functions**

In `execute_workflow` (~7560), add params before `timeout_seconds` and forward them:

```python
        return_on_chart_output: bool = False,
        timeout_seconds: float | None = None,
        workflow_name: str = "",
        workflow_description: str = "",
    ) -> ExecutionResult:
```

and in the `WorkflowExecutor(...)` construction inside it, add:

```python
        return_on_chart_output=return_on_chart_output,
        timeout_seconds=timeout_seconds,
        workflow_name=workflow_name,
        workflow_description=workflow_description,
    )
```

Do the same for `execute_workflow_streaming` (~8697): add `workflow_name: str = ""`, `workflow_description: str = ""` params and pass `workflow_name=workflow_name, workflow_description=workflow_description` into its `WorkflowExecutor(...)`.

Note: call sites (triggers, HTTP) need NOT change — when name/description are empty and `workflow_id` is set, `_get_workflow_metadata()` lazily fetches from the DB, covering all execution paths automatically.

- [ ] **Step 9: Run the format check + full executor-touching tests**

Run: `cd backend && uv run ruff format app/services/workflow_executor.py && uv run ruff check app/services/workflow_executor.py`
Expected: no errors.
Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_metadata_variables.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/tests/test_workflow_metadata_variables.py
git commit -m "feat: add workflow metadata expression variables to executor"
```

---

## Task 2: Expression-evaluate dialog parity (Feature A preview)

**Files:**
- Modify: `backend/app/services/expression_evaluator.py` (ctor ~1056; executor build ~1094)
- Modify: `backend/app/api/expressions.py` (evaluate endpoint ~292-337)
- Test: `backend/tests/test_expression_evaluator_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_expression_evaluator_service.py` (follow the file's existing style; import `uuid` if not present):

```python
    def test_workflow_metadata_variables_resolve_in_preview(self) -> None:
        wid = uuid.uuid4()
        service = ExpressionEvaluatorService(
            workflow_nodes=[],
            workflow_edges=[],
            workflow_id=wid,
            workflow_name="Daily Report",
            workflow_description="Sends a report",
            public_base_url="https://app.test",
        )
        self.assertEqual(service.evaluate("$workflowName", {}).result, "Daily Report")
        self.assertEqual(service.evaluate("$workflowPath", {}).result, f"/workflows/{wid}")
        self.assertEqual(
            service.evaluate("$workflowUrl", {}).result,
            f"https://app.test/workflows/{wid}",
        )

    def test_execution_id_is_empty_in_preview(self) -> None:
        service = ExpressionEvaluatorService(
            workflow_nodes=[], workflow_edges=[], workflow_id=uuid.uuid4()
        )
        self.assertEqual(service.evaluate("$executionId", {}).result, "")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_expression_evaluator_service.py -k workflow_metadata_variables_resolve_in_preview -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'workflow_id'`.

- [ ] **Step 3: Add service constructor params**

In `ExpressionEvaluatorService.__init__` (~1056), add params and store them:

```python
        vars_context: dict[str, Any] | None = None,
        workflow_id: "uuid.UUID | None" = None,
        workflow_name: str = "",
        workflow_description: str = "",
        public_base_url: str = "",
    ) -> None:
        self.workflow_nodes = workflow_nodes or []
        self.workflow_edges = workflow_edges or []
        self.credentials_context = credentials_context or {}
        self.global_variables_context = global_variables_context or {}
        self.vars_context = vars_context or {}
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.workflow_description = workflow_description
        self.public_base_url = public_base_url
```

Add `import uuid` at the top of the file if it is not already imported.

- [ ] **Step 4: Forward metadata to the preview executor**

In `evaluate()` (~1094), extend the `WorkflowExecutor(...)` construction:

```python
        executor = WorkflowExecutor(
            nodes=self.workflow_nodes,
            edges=self.workflow_edges,
            credentials_context=self.credentials_context,
            global_variables_context=self.global_variables_context,
            workflow_id=self.workflow_id,
            workflow_name=self.workflow_name,
            workflow_description=self.workflow_description,
            public_base_url=self.public_base_url,
        )
```

(`execution_id` is intentionally omitted, so `$executionId` resolves to `""` in preview.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_expression_evaluator_service.py -k "workflow_metadata_variables_resolve_in_preview or execution_id_is_empty_in_preview" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Wire the evaluate endpoint to pass real metadata**

In `backend/app/api/expressions.py`, add `Request` to the endpoint and build the base URL. Ensure imports at top include:

```python
from fastapi import Request
from app.services.hitl_service import build_public_base_url
```

Change the `evaluate_expression` signature (~292) to accept the raw request:

```python
async def evaluate_expression(
    request: ExpressionEvaluateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExpressionEvaluateResponse:
```

Then extend the service construction (~331):

```python
    service = ExpressionEvaluatorService(
        workflow_nodes=workflow_nodes,
        workflow_edges=workflow_edges,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        vars_context=vars_context,
        workflow_id=workflow.id,
        workflow_name=workflow.name or "",
        workflow_description=workflow.description or "",
        public_base_url=build_public_base_url(http_request),
    )
```

- [ ] **Step 7: Run evaluator tests + format**

Run: `cd backend && uv run ruff format app/services/expression_evaluator.py app/api/expressions.py && uv run ruff check app/services/expression_evaluator.py app/api/expressions.py`
Expected: no errors.
Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_expression_evaluator_service.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/expression_evaluator.py backend/app/api/expressions.py backend/tests/test_expression_evaluator_service.py
git commit -m "feat: expose workflow metadata variables in expression evaluate dialog"
```

---

## Task 3: DSL prompt documentation + reserved names

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Check for a DSL-sync guard test**

Run: `cd backend && grep -rln "WORKFLOW_DSL_SYSTEM_PROMPT\|workflow_dsl_prompt" tests/`
Expected: note any test that asserts prompt/sync invariants so the edits below keep it green.

- [ ] **Step 2: Add the five variables to the reserved node-label list**

In `backend/app/services/workflow_dsl_prompt.py`, find the reserved-label list (the line containing `` `input`, `n`, `date` `` in rule 38, "RESERVED NODE LABEL NAMES"). Append the new names inside that backtick list:

```
..., `input`, `n`, `date`, `workflowName`, `workflowDescription`, `workflowUrl`, `workflowPath`, `executionId`.
```

- [ ] **Step 3: Document the five system variables**

In the section that documents built-in variables (near where `now` / `UUID` / `$Date()` are described), add:

```
- `$workflowName` - Current workflow's name
- `$workflowDescription` - Current workflow's description
- `$workflowPath` - Relative path of the workflow, e.g. `/workflows/<id>`
- `$workflowUrl` - Absolute URL of the workflow, e.g. `https://<host>/workflows/<id>`
- `$executionId` - Current execution's runtime id. **Runtime-only**: empty in the expression preview dialog; populated only while a workflow is executing.
```

Add `workflowName`, `workflowDescription`, `workflowUrl`, `workflowPath`, `executionId` to the two "System fields:" enumeration lines that already list `input`, `now`, `n`.

- [ ] **Step 4: Run the DSL/sync guard tests + format**

Run: `cd backend && uv run ruff format app/services/workflow_dsl_prompt.py && uv run ruff check app/services/workflow_dsl_prompt.py`
Expected: no errors.
Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "dsl_prompt or dsl_sync or reserved" -v`
Expected: PASS (or "no tests ran" if none exist — acceptable).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "docs: document workflow metadata variables in DSL prompt + reserve names"
```

---

## Task 4: Frontend expression-dialog metadata

**Files:**
- Modify: `frontend/src/types/expression.ts` (after `DATE_BUILTINS`, ~217)
- Modify: `frontend/src/composables/useExpressionCompletion.ts` (import ~14; usage ~837)

- [ ] **Step 1: Add a `WORKFLOW_BUILTINS` completion list**

In `frontend/src/types/expression.ts`, immediately after the `DATE_BUILTINS` array (closing `];` at ~217), add:

```typescript
export const WORKFLOW_BUILTINS: CompletionSuggestion[] = [
  {
    label: "workflowName",
    insertText: "workflowName",
    type: "property",
    detail: "Workflow name",
    description: "Current workflow's name",
    propertyType: "string",
  },
  {
    label: "workflowDescription",
    insertText: "workflowDescription",
    type: "property",
    detail: "Workflow description",
    description: "Current workflow's description",
    propertyType: "string",
  },
  {
    label: "workflowPath",
    insertText: "workflowPath",
    type: "property",
    detail: "Workflow path",
    description: "Relative path, e.g. /workflows/<id>",
    propertyType: "string",
  },
  {
    label: "workflowUrl",
    insertText: "workflowUrl",
    type: "property",
    detail: "Workflow URL",
    description: "Absolute URL, e.g. https://<host>/workflows/<id>",
    propertyType: "string",
  },
  {
    label: "executionId",
    insertText: "executionId",
    type: "property",
    detail: "Execution id (runtime only)",
    description: "Runtime-only: populated only while executing",
    propertyType: "string",
  },
];
```

- [ ] **Step 2: Surface `WORKFLOW_BUILTINS` in the completion composable**

In `frontend/src/composables/useExpressionCompletion.ts`, add `WORKFLOW_BUILTINS` to the import from `@/types/expression` (~14, alongside `DATE_BUILTINS`). Then locate the block that filters `DATE_BUILTINS` (~837, `const matchingDateBuiltins = DATE_BUILTINS.filter(...)`) and add a sibling filter that contributes `WORKFLOW_BUILTINS` to the same suggestion output. Mirror exactly how `matchingDateBuiltins` is pushed into the returned suggestions list:

```typescript
      const matchingWorkflowBuiltins = WORKFLOW_BUILTINS.filter((f) =>
        f.label.toLowerCase().includes(query.toLowerCase()),
      );
```

Then include `...matchingWorkflowBuiltins` wherever `...matchingDateBuiltins` (or the equivalent push) is used so both lists surface together. Read the surrounding ~20 lines first to match the exact variable names (`query` / push target) used there.

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/expression.ts frontend/src/composables/useExpressionCompletion.ts
git commit -m "feat: add workflow metadata variables to expression completion"
```

---

## Task 5: Navigable execution deep-link → Bring to Canvas (Feature B)

**Files:**
- Modify: `frontend/src/router/index.ts` (editor route ~37-42)
- Modify: `frontend/src/views/EditorView.vue` (onMounted load block ~611-617; route.params.id watcher ~680-697)
- Test: `frontend/e2e/execution-deep-link.spec.ts` (create, when practical)

- [ ] **Step 1: Add the optional execution segment to the editor route**

In `frontend/src/router/index.ts`, change the editor route path:

```typescript
    {
      path: "/workflows/:id/:executionId?",
      name: "editor",
      component: () => import("@/views/EditorView.vue"),
      meta: { requiresAuth: true },
    },
```

- [ ] **Step 2: Add a deep-link loader helper in EditorView**

In `frontend/src/views/EditorView.vue` `<script setup>`, add a function (near the other load helpers). Ensure `workflowApi` is already imported (it is used elsewhere in this file) and `route` is available:

```typescript
async function bringExecutionFromRoute(): Promise<void> {
  const execId = route.params.executionId as string | undefined;
  if (!execId) return;
  try {
    const entry = await workflowApi.getWorkflowHistoryEntry(
      workflowId.value,
      execId,
    );
    workflowStore.loadHistoryInputs(
      entry.inputs as Record<string, unknown>,
      entry.node_results,
    );
  } catch {
    // Execution not found / not accessible: fall back to the plain workflow.
    // (Optional) surface a toast here if the project has a toast helper in scope.
  }
}
```

Note: verify `ServerExecutionHistory` (the return type of `getWorkflowHistoryEntry`) exposes `inputs` and `node_results`; if the property names differ, adjust the two field accesses accordingly.

- [ ] **Step 3: Call the loader after initial workflow load**

In the `onMounted` block, right after the existing `pendingHistoryInputs` handling (the `if (workflowStore.pendingHistoryInputs) { ... }` block, ~611-617), add:

```typescript
    await bringExecutionFromRoute();
```

- [ ] **Step 4: Call the loader after route-change reload**

In the `route.params.id` watcher (~680), after the workflow finishes reloading (after `loadedWorkflow = true;` at ~697 and the subsequent state assignments in that `try`), add:

```typescript
        await bringExecutionFromRoute();
```

- [ ] **Step 5: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: no errors.

- [ ] **Step 6: Add a Playwright E2E spec (when practical)**

Create `frontend/e2e/execution-deep-link.spec.ts` following the patterns in the existing specs under `frontend/e2e/` (reuse their auth/setup helpers and any existing helper that runs a workflow to create a history entry). The spec should:
1. Create/open a workflow and run it so an execution-history entry exists; capture its entry id (from the execution result or the history API).
2. Navigate to `/workflows/<id>/<entryId>`.
3. Assert the canvas shows the historical execution (node results / historical inputs visible), matching how existing history specs assert "Bring to Canvas".

Read one existing spec first to copy fixtures, selectors, and helpers exactly.

- [ ] **Step 7: Run the E2E spec**

Run: `./run_e2e.sh` (from repo root; or the project's documented single-spec invocation)
Expected: the new deep-link spec passes.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/router/index.ts frontend/src/views/EditorView.vue frontend/e2e/execution-deep-link.spec.ts
git commit -m "feat: bring execution onto canvas via /workflows/:id/:executionId deep link"
```

---

## Task 6: Documentation via heym-documentation skill

**Files:**
- Modify: reference docs under `frontend/src/docs/content/reference/` (exact pages selected by the skill)

- [ ] **Step 1: Invoke the documentation skill**

Use the `heym-documentation` skill to update docs for:
1. The expressions/variables reference — add `$workflowName`, `$workflowDescription`, `$workflowUrl`, `$workflowPath`, and `$executionId` (with the runtime-only note).
2. The execution-history / navigation reference — document that opening `/workflows/{id}/{executionId}` brings that execution onto the canvas.

- [ ] **Step 2: Typecheck (docs are TS-embedded content)**

Run: `cd frontend && bun run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs
git commit -m "docs: document workflow metadata variables and execution deep link"
```

---

## Final Verification

- [ ] **Run the full check suite**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh` (from repo root)
Expected: frontend lint/typecheck pass, backend ruff + tests pass.

- [ ] **Run E2E**

Run: `./run_e2e.sh`
Expected: all specs (including the new deep-link spec) pass.

---

## Notes / Decisions Locked In

- **Decoupled** per design: `$executionId` is a per-run uuid, NOT an execution-history id; `$workflowUrl`/`$workflowPath` are workflow-level (no execution segment). Feature B's route segment is an execution-history entry id resolved from history-UI links.
- **Sourcing name/description** uses the executor's existing lazy DB-fetch pattern (`_get_workflow_metadata`, mirroring `_get_workflow_name_for_log`) so no trigger call sites need threading. The evaluate dialog passes metadata explicitly (already async-loaded) to avoid sync DB access in the request handler.
- **No history-creation flow changes** (out of scope by design).
