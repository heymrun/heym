# Error Workflow, Time Saved & Analyzer Upgrades — Design

Date: 2026-06-28

## Summary

Three related additions to the workflow editor, surfaced primarily through the
workflow-level Properties panel (shown when no node is selected):

1. **On error, run workflow** — a workflow-level setting that runs another
   workflow when this workflow's run fails, unless the canvas already has a
   local error handler (`errorHandler` node).
2. **Time saved** — a manual per-run minutes estimate that is aggregated into a
   total "Time saved" stat on the Analytics dashboard.
3. **Workflow Analyzer upgrades** — the AI analysis report gains three explicit
   capabilities (error coverage, time saved, network-node error handling), and
   the Properties panel gains a **Run Analyzer** button when the canvas is
   non-empty but the analysis note is empty.

## Background / Current State

- **Recover mode**: `Workflow.auto_recover_runs` (bool) is rendered as the
  "Auto-recover runs" toggle in `PropertiesPanel.vue` when no node is selected.
- **Per-node error handling**: nodes support `onErrorEnabled` (continue-on-error
  branch) in `workflow_executor.py`. There is no workflow-level error workflow.
- **Local error handler**: the existing `errorHandler` node type is a "Global
  Error Catcher" — it auto-activates when ANY node throws, needs no incoming
  edge, and only one per workflow is expected. In the executor it is tracked via
  `self.error_handler_nodes`. This node is the "local error handler trigger".
- **Sub-workflow execution**: a `SubWorkflowExecution` mechanism plus
  `WorkflowExecutor` reuse already exists (agent `call_sub_workflow` tool and the
  `executeWorkflow` node), including an invocation-depth guard.
- **Analyzer**: `WORKFLOW_ANALYZE_SYSTEM_PROMPT` (in `ai_assistant.py`) streams a
  3-section Markdown report (Improvement areas / Purpose / What it does) into
  `AnalysisPanel.vue`, persisted as a per-workflow analysis note.
- **Analytics**: `WorkflowAnalyticsSnapshot` tracks executions / success / error
  / latency. `AnalyticsStats` and `WorkflowBreakdownItem` feed
  `AnalyticsDashboard.vue`. There is no time-saved concept today.

## Requirements & Decisions

- Error workflow config is **n8n-style**: pick another existing workflow and pass
  error context to it.
- The external error workflow runs only when: the top-level run ends with an
  **unhandled** failure (a node failed and was not caught — including caught but
  still erroring) **AND** the canvas has **no** `errorHandler` node **AND** an
  `error_workflow_id` is configured.
- "Time saved" = manual **minutes per run × successful runs**.
- Time saved is shown **only** as a single top total stat card on the Analytics
  dashboard (no per-workflow breakdown column).
- The **Run Analyzer** button only **opens** the Analysis panel (the user still
  picks an LLM model and clicks Analyze) — matching current analyzer behavior.

## Design

### 1. Data model (backend)

Add two nullable columns to `Workflow` (`backend/app/db/models.py`) with an
Alembic migration:

- `error_workflow_id: Mapped[uuid.UUID | None]` — `ForeignKey("workflows.id",
  ondelete="SET NULL")`, nullable, indexed.
- `minutes_saved_per_run: Mapped[float | None]` — nullable.

Schema updates (`backend/app/models/schemas.py`):

- `WorkflowUpdate`: add `error_workflow_id: UUID | None = None` and
  `minutes_saved_per_run: float | None = None`.
- `WorkflowResponse`: add both fields.

Validation: `error_workflow_id` must reference a workflow the user owns/can
access and must not equal the workflow's own id (no direct self-loop). Enforced
in the workflows update endpoint.

### 2. Error workflow execution (executor)

Hook point: after a **top-level** run completes with overall `status == "error"`
(an unhandled node failure remains).

Run the error workflow only when ALL hold:

- `self.error_handler_nodes` is empty (no local `errorHandler` node on canvas).
- This run is itself not an error-workflow / sub-workflow invocation
  (recursion/loop guard — reuse `sub_workflow_invocation_depth` and add an
  explicit `is_error_workflow_run` flag so an error workflow that itself fails
  cannot recurse).
- The workflow's `error_workflow_id` is set and resolves to an accessible
  workflow.

Behavior: load the target workflow and execute it through the existing
sub-workflow path, passing a context payload:

```
{
  "workflow_id": <failed workflow id>,
  "workflow_name": <failed workflow name>,
  "run_id": <failed run id>,
  "error": <error message>,
  "errorNode": <label of failed node>,
  "errorNodeType": <type of failed node>,
  "timestamp": <ISO 8601>
}
```

The error-workflow run is recorded as a `SubWorkflowExecution` (trigger source
e.g. `ERROR_WORKFLOW`) so it appears in execution history. Failures of the error
workflow itself are swallowed/logged and must never mask or alter the original
run's reported failure.

### 3. Properties panel (frontend)

In the workflow-level section of `PropertiesPanel.vue` (no node selected),
rendered above the existing "Auto-recover runs" block, all owner-gated like the
recover toggle:

- **On error, run workflow** — a `<select>` listing the user's other workflows
  (exclude the current workflow; include a "None" option). On change, call
  `workflowApi.update(wf.id, { error_workflow_id })` with optimistic
  update + rollback (same pattern as `onToggleAutoRecover`).
- **Estimated time saved per run (min)** — a numeric input bound to
  `minutes_saved_per_run`, saved via `workflowApi.update` on blur/change.
- **Run Analyzer** button — visible only when
  `currentWorkflow.nodes.length > 0` AND the analysis note is empty. Clicking
  sets `workflowStore.analysisPanelOpen = true` (opens `AnalysisPanel`); it does
  not auto-start analysis. The note's emptiness is derived from existing analysis
  note state (load on panel mount / store), so the Properties panel needs a
  lightweight "note is empty" signal — fetch the note's presence when the
  workflow loads, or expose it via the workflow store.

The list of selectable workflows reuses an existing workflows list API
(`workflowApi`), filtered to exclude the current id.

### 4. Time saved in Analytics

Backend (`backend/app/api/analytics.py` + `dashboard_data.py`/service):

- Compute `time_saved_minutes = Σ (workflow.minutes_saved_per_run ×
  snapshot.success_count)` over the queried range, joining the per-workflow rate
  onto aggregated success counts. Deleted-workflow snapshot rows
  (`workflow_id IS NULL`) contribute 0 (rate unknown).
- Add `time_saved_minutes: float` to `AnalyticsStats` (and the matching
  `AnalyticsStats` TS interface).

Frontend (`AnalyticsDashboard.vue`):

- Add a top "Time saved" stat card, formatted as hours/minutes (e.g. `12h 30m`).
- No per-workflow breakdown column.

### 5. Analyzer — three capabilities

Extend `WORKFLOW_ANALYZE_SYSTEM_PROMPT` and enrich the analyzed payload so the
model can reason about the new state. Pass into the workflow payload (or a small
adjunct block) booleans/values:

- `hasErrorHandler` — whether an `errorHandler` node exists on the canvas.
- `errorWorkflowConfigured` — whether `error_workflow_id` is set.
- `minutesSavedPerRun` — the configured estimate (or null).

The report (within or alongside "Improvement areas") must:

1. **Error coverage** — if there is no `errorHandler` node on the canvas AND no
   error workflow configured, explicitly state this gap and recommend adding
   error handling (errorHandler node and/or an error workflow).
2. **Time saved** — surface the configured estimate; if missing, recommend
   setting one so time-saved analytics populate.
3. **Network nodes** — for nodes that perform network I/O (e.g. `httpRequest`
   and integration/API nodes), recommend node-specific error handling
   (retry / onError) on those specific nodes.

### 6. Docs

Update documentation via the `heym-documentation` skill, including
`frontend/src/docs/content/reference/features.md` (the all-features reference),
covering: the error workflow setting, time-saved estimate + analytics card, and
the analyzer's new capabilities + Run Analyzer button.

## Testing

Backend (pytest, required):

- Error workflow invoked when run fails, no `errorHandler` node, and
  `error_workflow_id` set; error context payload shape.
- Error workflow **not** invoked when an `errorHandler` node exists.
- Error workflow **not** invoked when the run is itself an error-workflow / sub
  invocation (recursion guard); error-workflow failure does not mask the
  original failure.
- Time-saved aggregation = Σ(rate × success_count), with null/deleted handling.
- Schema/migration round-trip for the two new columns; update-endpoint
  validation (self-reference rejected, ownership enforced).

Frontend (Playwright where practical):

- Error-workflow selector and time-saved input render and persist for the owner.
- Run Analyzer button visible only when canvas non-empty AND note empty; opens
  the Analysis panel.

## Out of Scope / YAGNI

- Automatic time-saved estimation from execution duration.
- Per-workflow time-saved breakdown column.
- A new dedicated error-trigger node type (the existing `errorHandler` node
  serves as the local handler).
- Chaining/looping protection beyond the single-level recursion guard.
