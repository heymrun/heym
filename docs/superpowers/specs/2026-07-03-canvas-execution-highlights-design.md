# Canvas Execution Highlights — Design

**Date:** 2026-07-03
**Status:** Approved design (local; NOT committed per user instruction)
**Author:** Claude + Burak

## Goal

Give users a fast, at-a-glance way to see **what each node produced** in an
execution — shown as a dismissible popup in the **top-right of the Canvas** after
a live run, or after bringing a past run onto the Canvas via History → "Bring to
Canvas". The same popup also appears on the **dashboard / widget** surface,
where it surfaces the widget's run (with the final widget output prominent).

The mental model, per the user: *a convenience feature to see what a node output,
drawn top-to-bottom in execution order.*

## Locked scope decisions

- **Output-only records.** A highlighted node contributes its **output** (not a
  separate resolved-input record). This matches the "Highlight Node Output"
  property wording. Resolved-input capture is out of scope.
- **Per-node, independent rows.** No shared "loop group" selector. Each node is
  its own row. If a node ran multiple times (loop iterations / repeats), that row
  carries **its own** `‹ i / N ›` item selector; changing it swaps only that
  row's message.
- **Execution order, top → bottom.**
- **Single backend builder** as the single source of truth, feeding live runs,
  History reads, and widgets. Frontend just renders the payload.
- **One reusable popup** used on both the editor Canvas and the dashboard/widget
  surface.
- **No commits.** All code and this spec stay local; the user reviews and commits.

## Data model

A pure backend builder produces a `HighlightPayload` from `node_results` + the
workflow graph:

```
HighlightRecord {
  node_id: str
  node_label: str
  node_type: str
  kind: "input" | "output" | "agent" | "llm" | "final"
  runs: list[str]        # one message per execution; length 1 for single-run nodes
}

HighlightPayload {
  records: list[HighlightRecord]   # ordered by execution order (top → bottom)
}
```

- `runs.length == 1` → single-run node, render `Node — message…`.
- `runs.length > 1` → multi-run node, render `Node (N)` + inline `‹ i / N ›`.
- Full message text is sent; the frontend truncates to **250 chars + "…"** for
  the preview and renders the full text as Markdown on expand.

### Selection rules (which nodes become records)

All records are **output-only**. A node is included if it matches any of:

1. **Input node** — the workflow's entry node (no incoming edges; trigger / input
   types: `textInput`, `cron`, `*Trigger`, `fileUploadTrigger`, …). `kind:"input"`,
   `runs = [formatted run inputs]`. **Skipped when the run has no inputs** — e.g.
   dashboard widgets, which have no input node. *(auto)*
2. **Output node** — `node_type in {"output", "jsonOutputMapper", "chartOutput"}`
   (matches the executor's terminal-output set; `chartOutput` is the widget's
   drawn output). `kind:"output"`. *(auto)*
3. **Final fallback** — if the run contains **no** output-type node, the **last
   executed node**. `kind:"final"`. *(auto)*
4. **Agent / LLM** — `node_type in {"agent", "llm"}`. `kind:"agent"` / `"llm"`.
   *(auto — these never get the property toggle)*
5. **Flagged node** — `data.highlight === true` and `node_type not in
   {"agent","llm"}`. `kind:"output"`. *(manual)*

Node-type constants (`INPUT_NODE_TYPES`, `OUTPUT_NODE_TYPES`) live in the builder
module so the rules are testable and in one place.

### Dedup

Dedup by `node_id`. A node already auto-included (input / output / final /
agent / llm) never emits a second record even if it also has `highlight:true`.
This directly implements the user's "baştaki ve sondaki node'lar highlightlanırsa
duplicated record olmasın — zaten onlar ve ai/llm auto highlighted" requirement.
Kind precedence when a node qualifies for several: `input` → `output`/`final` →
`agent`/`llm` → flagged `output`.

### Multi-run collection

For each included node, collect its `node_results` rows in execution order into
`runs[]` (extract a display message from each row's `output`). No loop-branch
parsing and no cross-node coupling — each node's runs are independent.

- **Retry attempts excluded:** skip rows where `metadata.retry_stage ==
  "attempt_failed"` (mirrors the frontend `isRetryAttemptNodeResult` filter) so
  `runs` reflect real outputs, not failed retries.
- Ordering of records is by each node's **first** result-row index.

### Message extraction

Given a node output, produce a display string:

1. If the output is a string → use it.
2. Else if it's a dict with a string `text` / `message` / `content` / `output`
   field → use that field.
3. Else → `json.dumps(output, ensure_ascii=False)`.

Hard-cap each message at ~100k chars to bound payload size. The input record's
message is the formatted run inputs (fallback to the entry node's output if the
run inputs are empty).

## Backend wiring (3 seams, no DB migration)

- **New module** `backend/app/services/highlight/highlight_builder.py` — the pure
  `build_highlight_payload(node_results, nodes, edges, inputs) -> HighlightPayload`
  function. **New tests** `backend/tests/test_highlight_builder.py`.
- **Schemas** (`backend/app/models/schemas.py`): add `HighlightRecordSchema` /
  `HighlightPayloadSchema`; add an optional `highlight` field to
  `WorkflowExecuteResponse` (~L352), `ExecutionHistoryResponse` (~L361), and
  `ExecutionHistoryWithWorkflowResponse` (~L377).
- **Live run:** call the builder in the executor's final return assembly
  (`backend/app/services/workflow_executor.py`, the return dicts near
  ~L9051 / ~L9101 / ~L9128) and attach `highlight` to the response. The executor
  already holds nodes/edges/node_results, so this is a post-pass over data it
  already has — **no new `node_type` branches** in `_execute_node_logic`
  (respects the WorkflowExecutor modularity rule).
- **History (recompute-on-read):** in
  `backend/app/api/workflows.py` `get_execution_history_entry` (~L765), recompute
  the payload from the stored `history.node_results` + the workflow graph. This
  makes "Bring to Canvas" work with **no stored column and no migration**. Uses
  the workflow's current node `highlight` flags (acceptable for v1; structural
  auto-records don't depend on flags anyway).
- **Widgets:** in `backend/app/services/dashboard_data.py` `compute_widget_data`
  (called from `backend/app/api/dashboards.py`), compute the payload from the
  widget run's node_results and add `highlight` to `WidgetDataResponse`.

## Node property + DSL

- **`highlight` boolean** lives in node `data`, default `false` (absent = false).
  Documented in `backend/app/services/workflow_dsl_prompt.py` so AI autofill can
  set it. Example: `{ "highlight": false }`.
- It is a **static toggle** → **not** expression/dynamic-eligible, so no
  expression-dialog metadata and no autofill-field wiring beyond the DSL note.
- **"Highlight Node Output" toggle UI:** a small shared
  `frontend/src/components/Panels/propertiesPanel/nodes/HighlightNodeOutputToggle.vue`,
  rendered once by the dispatcher
  `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`
  for **every node type except `agent` and `llm`**. This avoids editing ~40
  per-node components and keeps `PropertiesPanel.vue` a thin shell.
- **BaseNode** (`frontend/src/components/Nodes/BaseNode.vue`) establishes the
  `false` default; optional subtle canvas badge when `highlight:true`.

## Frontend popup

- **New component** `frontend/src/components/Canvas/HighlightPopup.vue`, mounted
  **top-right** in `frontend/src/components/Canvas/WorkflowCanvas.vue`.
- **Store getter:** expose a `highlightPayload` getter on
  `frontend/src/stores/workflow.ts` derived from `executionResult.value.highlight`
  (the `highlight` field is added to the `ExecutionResult` type in
  `frontend/src/types/workflow.ts`, alongside `HighlightRecord` /
  `HighlightPayload` types).
- **Behavior:** auto-shown when a run / Bring-to-Canvas populates the execution
  log (`executionResult` non-empty with `highlight.records.length > 0`); **✕**
  closes it. Separate component from `DebugPanel.vue`.
- **Rows:** linear list in execution order. Single-run → `Node — message…`
  (250-char preview). Multi-run → `Node (N)` + inline `‹ i / N ›` (prev/next +
  small dropdown). Click a row → expands, renders the **selected run's full
  message as Markdown** via `frontend/src/lib/markdown.ts`, with a **Copy** button
  (reuse the existing clipboard pattern used in DebugPanel / ExecutionHistoryDialog).

```
┌─ Execution Highlights ──────────────── ✕ ┐
│ ▸ Text Input — {"topic":"AI agents", …}   │  input · 1 run
│ ▾ Agent (3)  ‹ 2 / 3 › — Item 2 result…   │  agent · 3 runs · item 2, expanded
│    ┌ …full markdown of run 2…    [Copy] ┐ │
│    └──────────────────────────────────┘  │
│ ▸ HTTP Request (3)  ‹ 1 / 3 › — {"…"}      │  3 runs
│ ▸ Output — # Report …                      │  1 run
└────────────────────────────────────────────┘
```

## Widget / dashboard surface

The same `HighlightPopup.vue`, mounted top-right on the dashboard/widget surface,
fed by `WidgetDataResponse.highlight` (`frontend/src/types/dashboard.ts` gains
the `highlight` field). Widgets have no input node, so the `chartOutput` node —
the widget's **drawn output** — is the prominent `kind:"output"` record, with any
agent/llm/flagged rows from the run listed above it in execution order. As the
user put it, "like in the dashboard tab".

## Testing & docs

- **Backend (required):** `test_highlight_builder.py` covering selection rules,
  dedup, execution-order, multi-run `runs[]` collection, retry-attempt exclusion,
  message extraction, and the input/final fallbacks. Focused cases on the History
  and widget seams. Run `./check.sh` before handing back.
- **Frontend:** lint + typecheck + manual verification (no Vitest harness in this
  repo). Optional Playwright E2E for the popup (open → expand → copy → multi-run
  selector) in `frontend/e2e/`.
- **Docs:** medium feature → update via the `heym-documentation` skill (the new
  `highlight` DSL field + the Execution Highlights popup). No new node type, so no
  new node page.

## Concrete integration points

| Area | File | Change |
| --- | --- | --- |
| Builder | `backend/app/services/highlight/highlight_builder.py` (new) | pure builder |
| Builder tests | `backend/tests/test_highlight_builder.py` (new) | unit tests |
| Schemas | `backend/app/models/schemas.py` (~341, 352, 361, 377) | add highlight schemas + fields |
| Live run | `backend/app/services/workflow_executor.py` (~9051/9101/9128) | attach highlight in return assembly |
| History | `backend/app/api/workflows.py` (~765/797) | recompute-on-read |
| Widgets | `backend/app/services/dashboard_data.py`, `backend/app/api/dashboards.py` | add highlight to widget data |
| DSL | `backend/app/services/workflow_dsl_prompt.py` | document `highlight` field |
| FE types | `frontend/src/types/workflow.ts` (823, 907), `frontend/src/types/dashboard.ts` (64) | HighlightRecord/Payload + `highlight` fields |
| FE store | `frontend/src/stores/workflow.ts` (52) | `highlightPayload` getter |
| Popup | `frontend/src/components/Canvas/HighlightPopup.vue` (new) | popup UI |
| Canvas mount | `frontend/src/components/Canvas/WorkflowCanvas.vue` | mount top-right |
| Toggle | `frontend/src/components/Panels/propertiesPanel/nodes/HighlightNodeOutputToggle.vue` (new) + `NodePropertiesForm.vue` | shared toggle for non-agent/llm |
| BaseNode | `frontend/src/components/Nodes/BaseNode.vue` | default + optional badge |
| Markdown | `frontend/src/lib/markdown.ts` | reuse for render |
| Widget surface | dashboard widget card / dashboard tab | mount popup fed by widget highlight |

## Out of scope (v1)

- Nested-loop compound selectors (a node inside nested loops still lists all its
  runs top-to-bottom via its own selector; no outer/inner cross-selectors).
- Capturing resolved node **inputs** (records are output-only).
- Storing the highlight payload in the DB (it is recomputed on read).

## Assumptions to confirm at review

- "Input node" = the workflow entry/trigger node; its record message = the run
  inputs.
- History reads use the workflow's **current** `highlight` flags (not a run-time
  snapshot). Structural auto-records are unaffected.
- Multi-run selector control = per-row `‹ i / N ›` prev/next + small dropdown.
