# Canvas Execution Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> ⚠️ **DO NOT COMMIT OR PUSH.** Per the user's instruction ("kodları commitleme localde tut"), leave every change in the working tree. Where a task says "Checkpoint", run the verification but **do not** `git commit`, `git add`, or `git push`. The user reviews and commits manually.

**Goal:** Add a dismissible top-right Canvas popup (and the same popup on the dashboard/widget surface) that shows, per node in execution order, what each node produced — with 250-char previews that expand to full Markdown + Copy, and a per-node item selector for nodes that ran multiple times.

**Architecture:** A single pure backend builder turns `node_results` + the workflow graph + run inputs into a `HighlightPayload` (a flat, execution-ordered list of output-only records; each record carries `runs[]`, one message per execution). The builder is the single source of truth, called from the live-run response, the history read endpoint (recompute-on-read, no DB migration), and the widget-data service. The frontend renders the payload with one reusable `HighlightPopup.vue`.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic + pytest (backend); Vue 3 `<script setup>` + TypeScript strict + Pinia + Tailwind (frontend).

**Spec:** `docs/superpowers/specs/2026-07-03-canvas-execution-highlights-design.md`

---

## File Structure

**Backend**
- `backend/app/services/highlight/__init__.py` (new) — package marker.
- `backend/app/services/highlight/highlight_builder.py` (new) — pure `build_highlight_payload(...)`.
- `backend/tests/test_highlight_builder.py` (new) — builder unit tests.
- `backend/app/models/schemas.py` (modify) — `HighlightRecordSchema`, `HighlightPayloadSchema`, `highlight` fields on 3 response models.
- `backend/app/api/workflows.py` (modify) — compute highlight for live run + history read.
- `backend/app/services/dashboard_data.py` (modify) — compute highlight for widgets.
- `backend/app/models/dashboard_schemas.py` or wherever `WidgetDataResponse` is defined (modify) — add `highlight` field.
- `backend/app/services/workflow_dsl_prompt.py` (modify) — document the `highlight` node field.
- `backend/tests/test_workflow_dsl_prompt_highlight.py` (new) — assert the DSL documents `highlight`.

**Frontend**
- `frontend/src/types/workflow.ts` (modify) — `HighlightRecord`, `HighlightPayload`, `highlight` on `ExecutionResult`.
- `frontend/src/types/dashboard.ts` (modify) — `highlight` on `WidgetDataResponse`.
- `frontend/src/stores/workflow.ts` (modify) — `highlightPayload` getter.
- `frontend/src/components/Canvas/HighlightPopup.vue` (new) — the reusable popup.
- `frontend/src/components/Canvas/WorkflowCanvas.vue` (modify) — mount popup top-right, fed by store getter.
- `frontend/src/components/Panels/propertiesPanel/nodes/HighlightNodeOutputToggle.vue` (new) — shared toggle.
- `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue` (modify) — render toggle for all non-agent/llm/sticky nodes.
- `frontend/src/components/Nodes/BaseNode.vue` (modify) — optional highlight badge.
- Dashboard widget surface (modify) — mount popup fed by `WidgetDataResponse.highlight`.

**Docs**
- Node/reference docs via the `heym-documentation` skill.

---

## Task 1: Highlight response schemas

**Files:**
- Modify: `backend/app/models/schemas.py` (after `NodeResultSchema`, ~line 349)

- [ ] **Step 1: Add the schemas**

In `backend/app/models/schemas.py`, immediately after the `NodeResultSchema` class (ends ~line 349), add:

```python
class HighlightRecordSchema(BaseModel):
    node_id: str
    node_label: str
    node_type: str
    kind: str  # "input" | "output" | "agent" | "llm" | "final"
    runs: list[str] = Field(default_factory=list)


class HighlightPayloadSchema(BaseModel):
    records: list[HighlightRecordSchema] = Field(default_factory=list)
```

- [ ] **Step 2: Add `highlight` to the three response models**

In the same file, add `highlight: HighlightPayloadSchema | None = None` to:
- `WorkflowExecuteResponse` (~line 352) — after `execution_history_id`.
- `ExecutionHistoryResponse` (~line 361) — after `recovered`.
- `ExecutionHistoryWithWorkflowResponse` (~line 377) — after `recovered`.

Example for `WorkflowExecuteResponse`:

```python
class WorkflowExecuteResponse(BaseModel):
    workflow_id: uuid.UUID
    status: str
    outputs: dict
    node_results: list[NodeResultSchema] = []
    execution_time_ms: float
    execution_history_id: uuid.UUID | None = None
    highlight: HighlightPayloadSchema | None = None
```

- [ ] **Step 3: Verify import + typecheck**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "from app.models.schemas import HighlightPayloadSchema, WorkflowExecuteResponse; print(WorkflowExecuteResponse.model_fields['highlight'])"`
Expected: prints a FieldInfo line mentioning `HighlightPayloadSchema` (no ImportError).

- [ ] **Step 4: Checkpoint (do NOT commit)** — leave changes in the working tree.

---

## Task 2: The highlight builder (pure function) — TDD

**Files:**
- Create: `backend/app/services/highlight/__init__.py`
- Create: `backend/app/services/highlight/highlight_builder.py`
- Test: `backend/tests/test_highlight_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_highlight_builder.py`:

```python
import unittest

from app.services.highlight.highlight_builder import build_highlight_payload


def _row(node_id, node_type, output, label=None, metadata=None):
    row = {
        "node_id": node_id,
        "node_label": label or node_id,
        "node_type": node_type,
        "status": "success",
        "output": output,
        "execution_time_ms": 1.0,
        "error": None,
    }
    if metadata:
        row["metadata"] = metadata
    return row


def _node(node_id, node_type, highlight=None, label=None):
    data = {"label": label or node_id}
    if highlight is not None:
        data["highlight"] = highlight
    return {"id": node_id, "type": node_type, "data": data}


class TestBuildHighlightPayload(unittest.TestCase):
    def test_input_node_uses_run_inputs(self):
        nodes = [_node("t1", "textInput"), _node("o1", "output")]
        rows = [_row("t1", "textInput", {"text": "hi"}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={"topic": "AI"})
        records = payload["records"]
        self.assertEqual(records[0]["node_id"], "t1")
        self.assertEqual(records[0]["kind"], "input")
        self.assertIn("topic", records[0]["runs"][0])

    def test_output_node_record(self):
        nodes = [_node("o1", "output")]
        rows = [_row("o1", "output", {"message": "final result"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][-1]["kind"], "output")
        self.assertEqual(payload["records"][-1]["runs"], ["final result"])

    def test_final_fallback_when_no_output_node(self):
        nodes = [_node("h1", "http")]
        rows = [_row("h1", "http", {"text": "last message"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][0]["kind"], "final")
        self.assertEqual(payload["records"][0]["runs"], ["last message"])

    def test_agent_and_llm_auto_highlighted(self):
        nodes = [_node("a1", "agent"), _node("l1", "llm"), _node("o1", "output")]
        rows = [
            _row("a1", "agent", {"text": "agent says"}),
            _row("l1", "llm", {"content": "llm says"}),
            _row("o1", "output", {"message": "done"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        kinds = {r["node_id"]: r["kind"] for r in payload["records"]}
        self.assertEqual(kinds["a1"], "agent")
        self.assertEqual(kinds["l1"], "llm")

    def test_flagged_node_output_only(self):
        nodes = [_node("h1", "http", highlight=True), _node("o1", "output")]
        rows = [_row("h1", "http", {"status": 200}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        ids = [r["node_id"] for r in payload["records"]]
        self.assertIn("h1", ids)

    def test_unflagged_middle_node_excluded(self):
        nodes = [_node("h1", "http"), _node("o1", "output")]
        rows = [_row("h1", "http", {"status": 200}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        ids = [r["node_id"] for r in payload["records"]]
        self.assertNotIn("h1", ids)

    def test_dedup_no_duplicate_for_auto_and_flagged(self):
        nodes = [_node("o1", "output", highlight=True)]
        rows = [_row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(len([r for r in payload["records"] if r["node_id"] == "o1"]), 1)

    def test_multi_run_collects_runs_in_order(self):
        nodes = [_node("a1", "agent")]
        rows = [
            _row("a1", "agent", {"text": "run 1"}),
            _row("a1", "agent", {"text": "run 2"}),
            _row("a1", "agent", {"text": "run 3"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        record = payload["records"][0]
        self.assertEqual(record["runs"], ["run 1", "run 2", "run 3"])

    def test_retry_attempts_excluded_from_runs(self):
        nodes = [_node("a1", "agent")]
        rows = [
            _row("a1", "agent", {"text": "failed"}, metadata={"retry_stage": "attempt_failed"}),
            _row("a1", "agent", {"text": "ok"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][0]["runs"], ["ok"])

    def test_message_extraction_json_fallback(self):
        nodes = [_node("h1", "http", highlight=True), _node("o1", "output")]
        rows = [_row("h1", "http", {"status": 200, "body": {"a": 1}}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        http_record = next(r for r in payload["records"] if r["node_id"] == "h1")
        self.assertIn("status", http_record["runs"][0])

    def test_records_in_execution_order(self):
        nodes = [_node("t1", "textInput"), _node("a1", "agent"), _node("o1", "output")]
        rows = [
            _row("t1", "textInput", {"text": "in"}),
            _row("a1", "agent", {"text": "mid"}),
            _row("o1", "output", {"message": "out"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={"x": 1})
        self.assertEqual([r["node_id"] for r in payload["records"]], ["t1", "a1", "o1"])

    def test_widget_no_input_node_no_input_record(self):
        nodes = [_node("c1", "chartOutput")]
        rows = [_row("c1", "chartOutput", {"type": "bar", "data": []})]
        payload = build_highlight_payload(rows, nodes, inputs=None)
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["kind"], "output")

    def test_trigger_type_is_input(self):
        nodes = [_node("s1", "slackTrigger"), _node("o1", "output")]
        rows = [_row("s1", "slackTrigger", {"text": "event"}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={"channel": "C1"})
        self.assertEqual(payload["records"][0]["kind"], "input")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_highlight_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.highlight'`.

- [ ] **Step 3: Create the package marker**

Create `backend/app/services/highlight/__init__.py`:

```python
```

(empty file)

- [ ] **Step 4: Implement the builder**

Create `backend/app/services/highlight/highlight_builder.py`:

```python
"""Pure builder for Canvas execution highlights.

Turns a run's ``node_results`` + workflow graph + run inputs into an
execution-ordered, output-only, per-node highlight payload. This is the single
source of truth used by live runs, history reads, and dashboard widgets.
"""

from __future__ import annotations

import json
from typing import Any

MESSAGE_CHAR_CAP = 100_000
INPUT_NODE_TYPES = {"textInput", "cron"}
OUTPUT_NODE_TYPES = {"output", "jsonOutputMapper", "chartOutput"}


def _is_input_type(node_type: str) -> bool:
    return node_type in INPUT_NODE_TYPES or node_type.endswith("Trigger")


def _extract_message(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        text = output
    elif isinstance(output, dict):
        text = ""
        for key in ("text", "message", "content", "output"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                text = value
                break
        if not text:
            try:
                text = json.dumps(output, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(output)
    else:
        try:
            text = json.dumps(output, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(output)
    if len(text) > MESSAGE_CHAR_CAP:
        text = text[:MESSAGE_CHAR_CAP]
    return text


def _is_retry_attempt(row: dict) -> bool:
    metadata = row.get("metadata") or {}
    return metadata.get("retry_stage") == "attempt_failed"


def build_highlight_payload(
    node_results: list[dict],
    nodes: list[dict],
    inputs: dict | None = None,
) -> dict:
    """Return ``{"records": [...]}`` — output-only, execution-ordered records.

    Rules (each node contributes at most one record):
      * input node (trigger / textInput) -> kind "input", message = run inputs
      * output-type node -> kind "output"
      * if no output-type node ran, the last executed node -> kind "final"
      * agent / llm -> kind "agent" / "llm" (auto, no toggle)
      * any node with ``data.highlight is True`` -> kind "output"
    Nodes that ran multiple times get one entry per run in ``runs`` (failed
    retry attempts excluded).
    """
    node_by_id: dict[str, dict] = {n.get("id"): n for n in nodes if n.get("id")}

    ordered_rows = [r for r in node_results if not _is_retry_attempt(r)]
    has_output_node = any(r.get("node_type") in OUTPUT_NODE_TYPES for r in ordered_rows)

    order: list[str] = []
    seen: set[str] = set()
    runs_by_node: dict[str, list[str]] = {}
    first_row_by_node: dict[str, dict] = {}
    for row in ordered_rows:
        nid = row.get("node_id")
        if not nid:
            continue
        if nid not in seen:
            seen.add(nid)
            order.append(nid)
            first_row_by_node[nid] = row
        runs_by_node.setdefault(nid, []).append(_extract_message(row.get("output")))

    last_executed_nid = order[-1] if order else None

    def kind_for(nid: str, ntype: str, flagged: bool) -> str | None:
        if _is_input_type(ntype):
            return "input"
        if ntype in OUTPUT_NODE_TYPES:
            return "output"
        if ntype == "agent":
            return "agent"
        if ntype == "llm":
            return "llm"
        if not has_output_node and nid == last_executed_nid:
            return "final"
        if flagged:
            return "output"
        return None

    records: list[dict] = []
    for nid in order:
        node = node_by_id.get(nid, {})
        first_row = first_row_by_node.get(nid, {})
        ntype = node.get("type") or first_row.get("node_type") or ""
        flagged = bool((node.get("data") or {}).get("highlight"))
        kind = kind_for(nid, ntype, flagged)
        if kind is None:
            continue
        label = (node.get("data") or {}).get("label") or first_row.get("node_label") or nid
        if kind == "input" and inputs:
            runs = [_extract_message(inputs)]
        else:
            runs = runs_by_node.get(nid) or [""]
        records.append(
            {
                "node_id": nid,
                "node_label": label,
                "node_type": ntype,
                "kind": kind,
                "runs": runs,
            }
        )

    return {"records": records}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_highlight_builder.py -v`
Expected: PASS (13 passed).

- [ ] **Step 6: Format + lint**

Run: `cd backend && uv run ruff format app/services/highlight/highlight_builder.py tests/test_highlight_builder.py && uv run ruff check app/services/highlight tests/test_highlight_builder.py`
Expected: no errors.

- [ ] **Step 7: Checkpoint (do NOT commit).**

---

## Task 3: Wire highlight into the live-run response

**Files:**
- Modify: `backend/app/api/workflows.py` (run endpoint, ~line 2474)

- [ ] **Step 1: Import the builder**

Near the top of `backend/app/api/workflows.py` (with the other `from app.services...` imports), add:

```python
from app.services.highlight.highlight_builder import build_highlight_payload
```

- [ ] **Step 2: Find every live-run response site**

Run: `cd backend && grep -n "WorkflowExecuteResponse(" app/api/workflows.py`
Add the `highlight` kwarg (Step 3 pattern) to **each** construction that returns a live run with `execution_result.node_results` in scope (the primary one is ~line 2474). Skip the `simple_response`/`JSONResponse` early-return branch — it intentionally returns raw outputs only.

- [ ] **Step 3: Populate `highlight` on the `WorkflowExecuteResponse`**

At the `WorkflowExecuteResponse(...)` construction (~line 2474), add the `highlight` kwarg. `workflow.nodes` and `enriched_inputs` are already in scope in this handler:

```python
        return WorkflowExecuteResponse(
            workflow_id=execution_result.workflow_id,
            status=execution_result.status,
            outputs=execution_result.outputs,
            node_results=execution_result.node_results,
            execution_time_ms=execution_result.execution_time_ms,
            execution_history_id=history_entry.id,
            highlight=build_highlight_payload(
                execution_result.node_results,
                workflow.nodes or [],
                enriched_inputs,
            ),
        )
```

> Note: `execution_result.node_results` here is a list of dicts (already serialized). If in this handler it is a list of Pydantic `NodeResultSchema`, convert first with `[nr.model_dump() for nr in execution_result.node_results]`. Confirm the type at implementation time by checking what `execution_result.node_results` holds.

- [ ] **Step 4: Verify the endpoint still imports/typechecks**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.api.workflows"`
Expected: no error.

- [ ] **Step 5: Run the existing workflow API tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "workflow and (run or execute)" -q`
Expected: PASS (no regressions).

- [ ] **Step 6: Checkpoint (do NOT commit).**

---

## Task 4: Wire highlight into history read (recompute-on-read)

**Files:**
- Modify: `backend/app/api/workflows.py` (`get_execution_history_entry`, ~line 765)

- [ ] **Step 1: Load the workflow graph and recompute highlight**

In `get_execution_history_entry` (~line 765), where `ExecutionHistoryResponse(...)` is built with `node_results=history.node_results or []` (~line 797), add a `highlight` kwarg computed from the stored rows plus the workflow's current nodes. The handler already has the `history` row; load its workflow's nodes (the workflow is typically fetched here — if not, fetch it by `history.workflow_id`). Build:

```python
        workflow_nodes = workflow.nodes if workflow and workflow.nodes else []
        highlight = build_highlight_payload(
            history.node_results or [],
            workflow_nodes,
            history.inputs or {},
        )
        return ExecutionHistoryResponse(
            id=history.id,
            workflow_id=history.workflow_id,
            inputs=history.inputs,
            outputs=history.outputs,
            node_results=history.node_results or [],
            status=history.status,
            execution_time_ms=history.execution_time_ms,
            started_at=history.started_at,
            trigger_source=history.trigger_source,
            recovered=history.recovered,
            highlight=highlight,
        )
```

> If `workflow` is not already loaded in this function, add a fetch:
> `workflow = (await db.execute(select(Workflow).where(Workflow.id == history.workflow_id))).scalar_one_or_none()`
> (`Workflow` and `select` are already imported in this module.)

- [ ] **Step 2: Cover the all-history endpoint too (Bring-to-Canvas can come from either dialog)**

Run: `cd backend && grep -n "ExecutionHistoryWithWorkflowResponse(" app/api/workflows.py`
For each construction that returns full `node_results` (the all-history "get one entry with workflow" path — used by `ExecutionHistoryAllDialog`), add the same `highlight=build_highlight_payload(<rows>, <workflow_nodes>, <inputs or {}>)` kwarg, loading the workflow's nodes the same way. Endpoints that return the **lightweight** list (`ExecutionHistoryListResponse` / `HistoryListResponse`, no `node_results`) do **not** get a highlight field — leave them untouched.

> Cross-check which endpoint the frontend "Bring to Canvas" actually calls:
> `cd frontend && grep -rn "bringToCanvas\|Bring to Canvas\|loadHistorical\|historicalExecutionResult" src/` and confirm the response type it consumes carries `highlight`. Both `ExecutionHistoryResponse` and `ExecutionHistoryWithWorkflowResponse` now do.

- [ ] **Step 3: Add a focused test for the history recompute scenario**

Create `backend/tests/test_highlight_history_scenario.py`:

```python
import unittest

from app.services.highlight.highlight_builder import build_highlight_payload


class TestHistoryHighlightScenario(unittest.TestCase):
    """History passes stored dict rows + the workflow's current nodes/flags."""

    def test_recompute_from_stored_rows_uses_current_flags(self):
        stored_rows = [
            {"node_id": "t1", "node_label": "Input", "node_type": "textInput",
             "status": "success", "output": {"text": "hi"}, "execution_time_ms": 1.0, "error": None},
            {"node_id": "h1", "node_label": "HTTP", "node_type": "http",
             "status": "success", "output": {"status": 200}, "execution_time_ms": 1.0, "error": None},
            {"node_id": "o1", "node_label": "Out", "node_type": "output",
             "status": "success", "output": {"message": "done"}, "execution_time_ms": 1.0, "error": None},
        ]
        # h1 is flagged on the CURRENT workflow graph
        nodes = [
            {"id": "t1", "type": "textInput", "data": {"label": "Input"}},
            {"id": "h1", "type": "http", "data": {"label": "HTTP", "highlight": True}},
            {"id": "o1", "type": "output", "data": {"label": "Out"}},
        ]
        payload = build_highlight_payload(stored_rows, nodes, {"topic": "AI"})
        ids = [r["node_id"] for r in payload["records"]]
        self.assertEqual(ids, ["t1", "h1", "o1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the scenario test**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_highlight_history_scenario.py -v`
Expected: PASS.

- [ ] **Step 5: Verify module import**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.api.workflows"`
Expected: no error.

- [ ] **Step 6: Checkpoint (do NOT commit).**

---

## Task 5: Wire highlight into dashboard widget data

**Files:**
- Modify: the module defining `WidgetDataResponse` (find with the grep below)
- Modify: `backend/app/services/dashboard_data.py` (`compute_widget_data`, ~line 188)

- [ ] **Step 1: Locate and extend `WidgetDataResponse`**

Run: `cd backend && grep -rn "class WidgetDataResponse" app/`
Add to that class:

```python
    highlight: "HighlightPayloadSchema | None" = None
```

Ensure `HighlightPayloadSchema` is imported in that module:

```python
from app.models.schemas import HighlightPayloadSchema
```

- [ ] **Step 2: Compute highlight in `compute_widget_data`**

In `backend/app/services/dashboard_data.py`, import the builder:

```python
from app.services.highlight.highlight_builder import build_highlight_payload
```

In `compute_widget_data`, after a run produces `result` (the object with `.node_results`), and where the `WidgetDataResponse(...)` is constructed, pass:

```python
        highlight=build_highlight_payload(
            [nr if isinstance(nr, dict) else nr.model_dump() for nr in (getattr(result, "node_results", []) or [])],
            widget_workflow.nodes or [],
            None,
        ),
```

> `widget_workflow` is the `Workflow` loaded at the top of `compute_widget_data` (`select(Workflow).where(Workflow.id == widget.workflow_id)`). Use whatever local variable name it is bound to. Widgets have no run inputs, so pass `inputs=None` — the builder emits no input record and the `chartOutput` node becomes the prominent `output` record.
> If `WidgetDataResponse` is returned from multiple branches (cache hit vs. miss), populate `highlight` on the run-producing branch(es); cached-payload branches without `node_results` may leave it `None`.

- [ ] **Step 3: Verify import**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "import app.services.dashboard_data"`
Expected: no error.

- [ ] **Step 4: Run dashboard tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "dashboard or widget" -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Checkpoint (do NOT commit).**

---

## Task 6: Document the `highlight` node field in the DSL

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`
- Test: `backend/tests/test_workflow_dsl_prompt_highlight.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_dsl_prompt_highlight.py`:

```python
import unittest

from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT


class TestDslDocumentsHighlight(unittest.TestCase):
    def test_prompt_mentions_highlight_field(self):
        self.assertIn("highlight", WORKFLOW_DSL_SYSTEM_PROMPT)
        # Documented as a boolean node-data flag, default false
        self.assertIn('"highlight"', WORKFLOW_DSL_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
```

> Confirm the exported constant name first: `grep -n "WORKFLOW_DSL_SYSTEM_PROMPT\|DSL_SYSTEM_PROMPT\|SYSTEM_PROMPT =" backend/app/services/workflow_dsl_prompt.py`. Use the actual exported prompt string constant in the import.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_dsl_prompt_highlight.py -v`
Expected: FAIL (assertion — `"highlight"` not present, or only present incidentally).

- [ ] **Step 3: Add the documentation**

In `backend/app/services/workflow_dsl_prompt.py`, in the section that documents common node-`data` fields (near where `disabled` is documented), add a concise note:

```text
- **highlight** (boolean, optional, default false): When true, this node's output is added to the Canvas "Execution Highlights" popup. Not needed on `agent`/`llm` nodes (their outputs are highlighted automatically) or on the input/output nodes (auto-highlighted). Example: { "highlight": false }
```

> ⚠️ Per the repo's expression/DSL rules, keep this change inside `WORKFLOW_DSL_SYSTEM_PROMPT` only. If there is a heymweb DSL-sync guard test that compares a shared prompt slice, run the full DSL prompt test file (below) and confirm no sync test breaks; the `highlight` note is a node-data field doc, which belongs in the synced DSL surface.

- [ ] **Step 4: Run the test + existing DSL prompt tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_dsl_prompt_highlight.py tests/test_plugin_dsl_prompt.py -v`
Expected: PASS (both files).

- [ ] **Step 5: Checkpoint (do NOT commit).**

---

## Task 7: Frontend types

**Files:**
- Modify: `frontend/src/types/workflow.ts` (near `ExecutionResult`, ~line 823)
- Modify: `frontend/src/types/dashboard.ts` (`WidgetDataResponse`, ~line 64)

- [ ] **Step 1: Add highlight types + field in `workflow.ts`**

Immediately above `export interface ExecutionResult` (~line 823), add:

```typescript
export type HighlightRecordKind = "input" | "output" | "agent" | "llm" | "final";

export interface HighlightRecord {
  node_id: string;
  node_label: string;
  node_type: string;
  kind: HighlightRecordKind;
  runs: string[];
}

export interface HighlightPayload {
  records: HighlightRecord[];
}
```

Then add to `ExecutionResult`:

```typescript
export interface ExecutionResult {
  workflow_id: string;
  status: "success" | "error" | "pending" | "awaiting_file_upload";
  outputs: Record<string, unknown>;
  execution_time_ms: number;
  node_results: NodeResult[];
  execution_history_id?: string | null;
  highlight?: HighlightPayload | null;
}
```

- [ ] **Step 2: Add highlight field in `dashboard.ts`**

Import the type at the top of `frontend/src/types/dashboard.ts`:

```typescript
import type { HighlightPayload } from "@/types/workflow";
```

Add to `WidgetDataResponse`:

```typescript
export interface WidgetDataResponse {
  widget_id: string;
  payload: ChartPayload | null;
  cached: boolean;
  computed_at: string | null;
  error?: string | null;
  highlight?: HighlightPayload | null;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Checkpoint (do NOT commit).**

---

## Task 8: Store getter for the highlight payload

**Files:**
- Modify: `frontend/src/stores/workflow.ts` (~line 52 and the store's return object)

- [ ] **Step 1: Add the computed**

Ensure `computed` is imported from `vue` (it almost certainly already is). Near `const executionResult = ref<ExecutionResult | null>(null);` (~line 52), add:

```typescript
  const highlightPayload = computed<HighlightPayload | null>(
    () => executionResult.value?.highlight ?? null,
  );
```

Import the type at the top (extend the existing `@/types/workflow` import):

```typescript
import type { /* existing… */ HighlightPayload } from "@/types/workflow";
```

- [ ] **Step 2: Export it from the store**

In the store's `return { ... }` object, add `highlightPayload,`.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Checkpoint (do NOT commit).**

---

## Task 9: The `HighlightPopup.vue` component

**Files:**
- Create: `frontend/src/components/Canvas/HighlightPopup.vue`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/Canvas/HighlightPopup.vue`:

```vue
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Check, ChevronLeft, ChevronRight, Copy, X } from "lucide-vue-next";
import { renderMarkdown } from "@/lib/markdown";
import type { HighlightPayload, HighlightRecord } from "@/types/workflow";

const props = defineProps<{ payload: HighlightPayload | null }>();

const PREVIEW_LIMIT = 250;

const dismissed = ref(false);
const expanded = ref<Set<number>>(new Set());
const runIndexById = ref<Record<string, number>>({});
const copiedIndex = ref<number | null>(null);

const records = computed<HighlightRecord[]>(() => props.payload?.records ?? []);
const visible = computed<boolean>(() => !dismissed.value && records.value.length > 0);

const kindLabel: Record<HighlightRecord["kind"], string> = {
  input: "Input",
  output: "Output",
  agent: "Agent",
  llm: "LLM",
  final: "Output",
};

watch(
  () => props.payload,
  () => {
    dismissed.value = false;
    expanded.value = new Set();
    runIndexById.value = {};
    copiedIndex.value = null;
  },
);

function runIndex(record: HighlightRecord): number {
  const idx = runIndexById.value[record.node_id] ?? 0;
  return Math.min(Math.max(idx, 0), Math.max(record.runs.length - 1, 0));
}

function setRunIndex(record: HighlightRecord, next: number): void {
  const clamped = Math.min(Math.max(next, 0), record.runs.length - 1);
  runIndexById.value = { ...runIndexById.value, [record.node_id]: clamped };
}

function currentRun(record: HighlightRecord): string {
  return record.runs[runIndex(record)] ?? "";
}

function preview(text: string): string {
  const trimmed = text.replace(/\s+/g, " ").trim();
  if (trimmed.length <= PREVIEW_LIMIT) {
    return trimmed;
  }
  return `${trimmed.slice(0, PREVIEW_LIMIT)}...`;
}

function toggle(index: number): void {
  const next = new Set(expanded.value);
  if (next.has(index)) {
    next.delete(index);
  } else {
    next.add(index);
  }
  expanded.value = next;
}

async function copy(record: HighlightRecord, index: number): Promise<void> {
  try {
    await navigator.clipboard.writeText(currentRun(record));
    copiedIndex.value = index;
    window.setTimeout(() => {
      if (copiedIndex.value === index) {
        copiedIndex.value = null;
      }
    }, 1500);
  } catch {
    // clipboard unavailable; ignore
  }
}
</script>

<template>
  <div
    v-if="visible"
    class="absolute right-4 top-4 z-20 flex max-h-[70vh] w-80 flex-col rounded-lg border border-border bg-background shadow-lg"
  >
    <div class="flex items-center justify-between border-b border-border px-3 py-2">
      <span class="text-sm font-medium">Execution Highlights</span>
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground"
        aria-label="Close highlights"
        @click="dismissed = true"
      >
        <X class="h-4 w-4" />
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-2">
      <div
        v-for="(record, index) in records"
        :key="`${record.node_id}-${index}`"
        class="mb-1 rounded-md border border-transparent hover:border-border"
      >
        <button
          type="button"
          class="flex w-full items-start gap-2 px-2 py-1.5 text-left"
          @click="toggle(index)"
        >
          <span
            class="mt-0.5 shrink-0 rounded bg-muted px-1 text-[10px] uppercase leading-4 text-muted-foreground"
          >
            {{ kindLabel[record.kind] }}
          </span>
          <span class="min-w-0 flex-1 text-xs">
            <span class="font-medium">
              {{ record.node_label
              }}<template v-if="record.runs.length > 1"> ({{ record.runs.length }})</template>
            </span>
            <span class="text-muted-foreground"> — {{ preview(currentRun(record)) }}</span>
          </span>
        </button>

        <div v-if="expanded.has(index)" class="px-2 pb-2">
          <div
            v-if="record.runs.length > 1"
            class="mb-1 flex items-center gap-1 text-xs text-muted-foreground"
          >
            <button
              type="button"
              class="rounded p-0.5 hover:bg-muted disabled:opacity-40"
              :disabled="runIndex(record) === 0"
              @click.stop="setRunIndex(record, runIndex(record) - 1)"
            >
              <ChevronLeft class="h-3 w-3" />
            </button>
            <select
              class="rounded border border-border bg-background px-1 py-0.5 text-xs"
              :value="runIndex(record)"
              @change.stop="setRunIndex(record, Number(($event.target as HTMLSelectElement).value))"
            >
              <option v-for="(_, i) in record.runs" :key="i" :value="i">
                {{ i + 1 }} / {{ record.runs.length }}
              </option>
            </select>
            <button
              type="button"
              class="rounded p-0.5 hover:bg-muted disabled:opacity-40"
              :disabled="runIndex(record) === record.runs.length - 1"
              @click.stop="setRunIndex(record, runIndex(record) + 1)"
            >
              <ChevronRight class="h-3 w-3" />
            </button>
          </div>

          <div class="relative rounded-md bg-muted/50 p-2">
            <button
              type="button"
              class="absolute right-1 top-1 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Copy message"
              @click.stop="copy(record, index)"
            >
              <Check v-if="copiedIndex === index" class="h-3.5 w-3.5" />
              <Copy v-else class="h-3.5 w-3.5" />
            </button>
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="max-w-none break-words pr-6 text-xs leading-relaxed [&_a]:underline [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_p]:my-1 [&_pre]:overflow-x-auto"
              v-html="renderMarkdown(currentRun(record))"
            />
            <!-- eslint-enable vue/no-v-html -->
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS. (If `renderMarkdown` is not the exported name, use the correct export from `frontend/src/lib/markdown.ts` — `renderMarkdown` was confirmed present.)

- [ ] **Step 3: Checkpoint (do NOT commit).**

---

## Task 10: Mount the popup on the Canvas

**Files:**
- Modify: `frontend/src/components/Canvas/WorkflowCanvas.vue`

- [ ] **Step 1: Import + wire the store getter**

In `WorkflowCanvas.vue` `<script setup>`, import the component and read the getter from the workflow store (the store instance almost certainly already exists in this file — reuse it):

```typescript
import HighlightPopup from "@/components/Canvas/HighlightPopup.vue";
```

Add a computed bound to the store getter (use the existing store variable name in this file, e.g. `workflowStore`):

```typescript
const highlightPayload = computed(() => workflowStore.highlightPayload);
```

- [ ] **Step 2: Render it inside the canvas wrapper**

Place `<HighlightPopup :payload="highlightPayload" />` inside the Vue Flow container element (the same positioned wrapper that holds the canvas), so its `absolute right-4 top-4` anchors to the canvas. Add it as the last child of that wrapper:

```vue
    <HighlightPopup :payload="highlightPayload" />
```

> Verify the parent element is `position: relative` (Vue Flow's container is). If the popup anchors to the viewport instead of the canvas, wrap the canvas area in a `class="relative"` container or move the mount to the nearest relatively-positioned canvas wrapper.

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Manual smoke test**

Run the app (`./run.sh`), open a workflow, run it. Expect the "Execution Highlights" popup top-right showing input + agent/llm + output records; click a row → expands to Markdown with Copy; run a workflow with a loop → the looped node shows `(N)` + a working `‹ i / N ›` selector. Then History → "Bring to Canvas" on a past run → popup shows that run's highlights.

- [ ] **Step 5: Checkpoint (do NOT commit).**

---

## Task 11: "Highlight Node Output" toggle + wiring

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/HighlightNodeOutputToggle.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`

- [ ] **Step 1: Create the shared toggle**

Create `frontend/src/components/Panels/propertiesPanel/nodes/HighlightNodeOutputToggle.vue` (mirrors the `allowDownstream` checkbox pattern in `OutputNodeProperties.vue`):

```vue
<script setup lang="ts">
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, updateNodeData } = usePropertiesPanelContext();
</script>

<template>
  <div v-if="selectedNode" class="mt-4 border-t border-border pt-3">
    <div class="flex items-center gap-2">
      <input
        id="node-highlight-output"
        type="checkbox"
        class="h-4 w-4 rounded border-input bg-background"
        :checked="!!selectedNode.data.highlight"
        @change="updateNodeData('highlight', ($event.target as HTMLInputElement).checked)"
      >
      <Label for="node-highlight-output" class="text-sm font-normal">
        Highlight Node Output
      </Label>
    </div>
    <p class="mt-1 pl-6 text-xs text-muted-foreground">
      Show this node's output in the Canvas Execution Highlights popup.
    </p>
  </div>
</template>
```

- [ ] **Step 2: Wire it into the dispatcher**

In `NodePropertiesForm.vue`, import it in `<script setup>`:

```typescript
import HighlightNodeOutputToggle from "./HighlightNodeOutputToggle.vue";
```

At the **end** of the `<template>` (after the `PluginNodeProperties` `v-else-if`, as a new sibling root node), add:

```vue
  <HighlightNodeOutputToggle
    v-if="selectedNode && !['agent', 'llm', 'sticky'].includes(selectedNode.type)"
  />
```

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Manual check**

Select an HTTP node → "Highlight Node Output" checkbox appears, toggles, and persists in the node data. Select an Agent or LLM node → the checkbox is **absent**.

- [ ] **Step 5: Checkpoint (do NOT commit).**

---

## Task 12: BaseNode default + optional badge

**Files:**
- Modify: `frontend/src/components/Nodes/BaseNode.vue`

- [ ] **Step 1: Ensure the default is falsey (no code needed if absent = false)**

`highlight` is read as `!!selectedNode.data.highlight`, so an absent value already means `false` — no default assignment required. Only add an explicit default if node-creation code elsewhere requires all data keys present (it does not here).

- [ ] **Step 2 (optional): Add a subtle badge when `highlight` is true**

If you want a canvas affordance, in `BaseNode.vue` add a small indicator gated on `props.data?.highlight === true` (mirror how BaseNode renders other small status badges). Keep it visually minimal (e.g. a tiny dot/eye icon). This is optional polish; skip if it complicates the node header.

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Checkpoint (do NOT commit).**

---

## Task 13: Mount the popup on the dashboard/widget surface

**Files:**
- Modify: the dashboard widget card / dashboard tab component that renders a widget's computed data (identify with the grep below)

- [ ] **Step 1: Find where widget data is rendered**

Run: `cd frontend && grep -rn "WidgetDataResponse\|widget.*payload\|computeWidget\|fetchWidgetData\|\.payload" src/components/Dashboards`
Identify the component that holds a widget's `WidgetDataResponse` (it renders `payload` as a chart). That response now also carries `highlight`.

- [ ] **Step 2: Mount the popup fed by the widget's highlight**

In that component, import and render the same popup, anchored top-right of the widget/dashboard container (ensure the container is `relative`):

```vue
<script setup lang="ts">
import HighlightPopup from "@/components/Canvas/HighlightPopup.vue";
// … existing imports …
</script>
```

```vue
    <HighlightPopup :payload="widgetData?.highlight ?? null" />
```

Use the actual local variable holding the `WidgetDataResponse`. Per the user, on this surface the popup surfaces the widget's run with the `chartOutput` (drawn output) as the prominent record.

> If a dashboard shows many widgets at once, prefer mounting the popup for the **focused/expanded** widget rather than one per card, to avoid stacking multiple popups. Confirm the desired placement with the user during review if the dashboard renders a grid of widgets simultaneously.

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Manual check**

Open the dashboard tab, trigger/refresh a widget that runs its workflow → the popup appears top-right showing the widget's run highlights with the drawn output prominent.

- [ ] **Step 5: Checkpoint (do NOT commit).**

---

## Task 14: Documentation (heym-documentation skill)

**Files:**
- Docs under `frontend/src/docs/content/...` as directed by the skill.

- [ ] **Step 1: Invoke the docs skill**

Use the `heym-documentation` skill to document: (a) the new `highlight` node-data field (boolean, default false; not on agent/llm; auto for input/output/agent/llm), and (b) the Canvas "Execution Highlights" popup (what it shows, per-node item selector, Copy, availability on canvas + Bring-to-Canvas + dashboard widgets). No new node type, so no new node page — update the relevant reference/feature docs the skill identifies.

- [ ] **Step 2: Frontend doc checks**

Run: `cd frontend && bun run typecheck` (docs manifest/content compiles).
Expected: PASS.

- [ ] **Step 3: Checkpoint (do NOT commit).**

---

## Task 15: Full verification pass

- [ ] **Step 1: Backend format + lint + tests**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: frontend lint/typecheck PASS, backend ruff PASS, backend tests PASS (including the new `test_highlight_builder.py`, `test_highlight_history_scenario.py`, `test_workflow_dsl_prompt_highlight.py`).

> `./check.sh` applies `ruff format` — if it reformats files, that is expected; leave the diffs in the working tree (do NOT commit).

- [ ] **Step 2: Manual end-to-end walkthrough**

1. Run a workflow with input → agent → output: popup shows Input, Agent, Output rows; expand renders Markdown; Copy works.
2. Run a workflow with a loop over N items with a flagged HTTP node and an agent inside: those rows show `(N)` and the `‹ i / N ›` selector swaps only that row.
3. Flag a plain node (`Highlight Node Output`) and run: it appears; flag an output node and confirm no duplicate row (dedup).
4. History → "Bring to Canvas": popup shows the past run.
5. Dashboard widget refresh: popup shows the widget run with drawn output prominent.
6. ✕ closes the popup; a new run re-opens it.

- [ ] **Step 3: Report status to the user (do NOT commit or push).**

Summarize what passed and hand back for the user to review and commit.

---

## Notes on scope & assumptions (from the spec)

- Records are **output-only**; no resolved-input capture.
- Loop handling is **per-node** (`runs[]` + per-row selector), no shared loop-group selector, no nested-loop compound selectors.
- History reads use the workflow's **current** `highlight` flags; structural auto-records (input/output/final/agent/llm) don't depend on flags.
- The builder ignores `edges` (not needed for these rules) — signature is `build_highlight_payload(node_results, nodes, inputs)`.
