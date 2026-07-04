# Design: Workflow Metadata Expression Variables + Execution Deep-Link Bring-to-Canvas

Date: 2026-07-03

## Summary

Two independent features that happen to share a URL format:

**Feature A — Workflow metadata expression variables.** Add five new flat top-level
expression variables (`$workflowName`, `$workflowDescription`, `$workflowUrl`,
`$workflowPath`, `$executionId`) alongside the existing `$now` / `$date` / `$UUID`
built-ins, so workflows can reference their own metadata inside expressions.
`$executionId` is populated only at runtime.

**Feature B — Navigable execution deep-link.** When a URL of the form
`/workflows/{workflow_id}/{executionId}` is opened as a navigable route, the referenced
execution history (which already exists) is brought onto the canvas, reusing the existing
"Bring to Canvas" (`loadHistoryInputs`) path.

These two features are deliberately **decoupled**: `$executionId` is an ephemeral runtime
run id and is NOT guaranteed to equal any execution-history id, and `$workflowUrl` points
at the workflow (no execution segment). Feature B's route segment is an execution-history
entry id resolved from history-UI links.

## Motivation

- Workflows frequently need to reference their own identity (name, description, canonical
  URL/path) and the current execution id inside expressions — e.g. for notifications,
  logging, or links back into the app.
- Users want to jump straight to a specific past execution on the canvas via a shareable
  URL, the same way the Execution History dialog's "Bring to Canvas" works today.

## Feature A — Workflow Metadata Expression Variables

### Variables

All five are **flat top-level** (matching the existing `now` / `date` / `UUID` style, per
the chosen convention) and injected in `WorkflowExecutor._build_context`
(`backend/app/services/workflow_executor.py`, near line 5444 where `now`/`UUID` are set).
String values are wrapped as `DotStr` so string methods (`.upper()`, `.replace()`, etc.)
work consistently with other string built-ins.

| Variable | Value | Source |
|---|---|---|
| `$workflowName` | Workflow name, `""` if unknown | New executor param from `workflow.name` |
| `$workflowDescription` | Workflow description, `""` if unknown | New executor param from `workflow.description` |
| `$workflowPath` | `/workflows/{workflow_id}`, `""` if no workflow id | Derived from existing `self.workflow_id` |
| `$workflowUrl` | `{base}/workflows/{workflow_id}`, `""` if no workflow id | `self._base_url` (already passed as `public_base_url`), fallback `settings.frontend_url` |
| `$executionId` | Ephemeral runtime run id (uuid4 hex). **Runtime-only**; `""` during expression preview | Executor self-generates once per `execute()` |

Notes:
- `$workflowUrl` is `$base` + `$workflowPath`. `base` is the existing `public_base_url`
  already threaded into the executor as `self._base_url`; when empty, fall back to
  `settings.frontend_url` (`backend/app/config.py:51`, default `http://localhost:4017`).
  Trailing slashes are normalized so the result has exactly one `/` between base and path.
- When `workflow_id` is `None` (ad-hoc / preview executions), `$workflowPath` and
  `$workflowUrl` resolve to `""`.

### Executor wiring

- Add constructor params to `WorkflowExecutor.__init__`
  (`backend/app/services/workflow_executor.py:1709`):
  - `workflow_name: str = ""`
  - `workflow_description: str = ""`
  - `execution_id: str = ""` (optional; when empty and this is a real run, the executor
    generates one — stored on `self` so all nodes in the run see the same value).
- Store as `self.workflow_name`, `self.workflow_description`, `self.execution_id`.
- Thread the new params through the `run_workflow` helper wrappers
  (`backend/app/services/workflow_executor.py:7573`, `:8697`) so API call sites can pass
  `workflow.name` / `workflow.description`.
- Real-run API call sites (the primary sync, streaming, and async execution entry points in
  `backend/app/api/workflows.py`, and other executor construction sites that have the
  `Workflow` record in hand) pass `workflow_name=workflow.name`,
  `workflow_description=workflow.description`. Sites without a workflow record simply omit
  them (defaults to `""`).

### Expression evaluator parity

`ExpressionEvaluatorService` (`backend/app/services/expression_evaluator.py`) must mirror
the executor so the `/expressions/evaluate` dialog previews the same values (per the
executor-vs-dialog consistency rule in AGENTS.md):

- `$workflowName`, `$workflowDescription`, `$workflowPath`, `$workflowUrl` resolve using the
  workflow record the evaluator loads (name/description) and its base URL.
- `$executionId` resolves to `""` in the dialog, because no execution is running. This is
  the visible signal that it is runtime-only.

### DSL prompt & reserved names

In `backend/app/services/workflow_dsl_prompt.py`:
- Document the five new system variables, with an explicit note that `$executionId` is
  populated only at runtime (empty during expression preview).
- Add `workflowName`, `workflowDescription`, `workflowUrl`, `workflowPath`, `executionId`
  (and case variations, per the existing convention) to the **reserved node-label names**
  list so users cannot shadow them with node labels.

### Frontend expression-dialog metadata

Add the five variables to the frontend system-variable metadata that powers the expression
dialog's `1/n` navigation and autofill field discovery (the same list that currently
surfaces `now` / `n` / `vars` etc.; exact file to be pinned during planning — candidates
under `frontend/src/composables/useExpressionCompletion.ts` /
`frontend/src/types/expression.ts` and related expression metadata). `$executionId` is
labeled as runtime-only in its description/hint.

## Feature B — Navigable Execution Deep-Link → Bring to Canvas

### Route

- Extend the workflow editor route to accept an optional execution segment:
  `path: "/workflows/:id/:executionId?"` (`frontend/src/router/index.ts:38`). Same
  `EditorView` component; `:executionId` is an execution-history entry id (UUID).

### Load behavior

In `frontend/src/views/EditorView.vue`, the workflow is loaded via
`workflowStore.loadWorkflow(id)` (around line 594) plus a `route.params.id` watcher
(around line 681). Add handling for `route.params.executionId`:

1. After the workflow finishes loading, if `executionId` is present, fetch
   `GET /workflows/{id}/history/{executionId}` — the existing endpoint
   `get_workflow_execution_history_entry` (`backend/app/api/workflows.py:2652`), which
   returns `ExecutionHistoryResponse` with `inputs`, `node_results`, and highlight payload.
2. Call `workflowStore.loadHistoryInputs(entry.inputs, entry.node_results, entry.result)` —
   the exact path used by `ExecutionHistoryDialog.bringToCanvas`
   (`frontend/src/components/Panels/ExecutionHistoryDialog.vue:588`), which loads the
   historical inputs and results onto the canvas.
3. On 404 / fetch error: show a toast and fall back to the plain workflow (no crash). The
   `:id` segment still renders the workflow normally.

Loading is idempotent, so a page refresh re-applies the same history without side effects.
The `:executionId` param is left in the URL (it is a shareable deep link).

## Testing

- **Backend (required):**
  - Extend `backend/tests/test_expression_evaluator_service.py`: the five variables resolve;
    `$workflowUrl` / `$workflowPath` format correctly with and without `workflow_id` and
    with/without a base URL (slash normalization); `$executionId` is `""` in the dialog.
  - Executor-level test that `$executionId` is a non-empty, stable-per-run value during a
    real execution, and that `$workflowName` / `$workflowDescription` reflect the passed
    metadata.
  - Existing DSL sync / reserved-name guard tests continue to pass with the new reserved
    names.
- **Frontend E2E (Playwright, when practical):** a spec that navigates to
  `/workflows/{id}/{executionId}` and asserts the execution is brought onto the canvas
  (node results / historical inputs visible). No Vitest / component tests (repo convention).

## Documentation

Update docs via the `heym-documentation` skill:
- Expressions / variables reference: add the five new variables, with the `$executionId`
  runtime-only note.
- Execution history / deep-link reference: document that `/workflows/{id}/{executionId}`
  brings that execution onto the canvas.

## Out of Scope (YAGNI)

- No pre-generated execution id threaded into `ExecutionHistory` rows (decoupled approach
  chosen). History creation flow is untouched.
- `$workflowUrl` does not deep-link to a specific run (no execution segment).
- No "Bring to Canvas" button inside the expression dialog — Feature B is route-driven only.

## Open Items to Pin During Planning

- Exact frontend file(s) holding the system-variable metadata list for the expression
  dialog.
- The complete set of `WorkflowExecutor(...)` construction sites in
  `backend/app/api/workflows.py` (and elsewhere) that have a `Workflow` record and should
  pass `workflow_name` / `workflow_description`.
