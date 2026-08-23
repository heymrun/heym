# htmlOutputMapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Heym workflow serve an HTML page over its execute webhook, reachable with any of GET/POST/PUT/DELETE, and say so on the dashboard.

**Architecture:** A new terminal node `htmlOutputMapper` renders one expression-capable HTML template and emits `{html, statusCode, contentType}`. A pure helper module decides, from the graph plus the node results, whether `/execute` should answer with `HTMLResponse` instead of `JSONResponse`. A new `workflows.http_method` column (default `POST`) is enforced at the route and drives both cURL generators. `compute_trigger_status` gains a `web` verdict.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + pytest (backend); Vue 3 `<script setup>` + TypeScript strict + Pinia + Vitest (frontend); Next.js + Bun (heymweb).

**Spec:** `docs/superpowers/specs/2026-08-23-html-output-mapper-design.md`
**Baseline:** `c7af349a` (PR #486). Alembic head: `113_add_folder_description`.

**Conventions that apply to every task:**
- Run backend tests as `HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest ...` from `backend/`. The OTel prefix is mandatory — a `.env` with `HEYM_OTEL_ENABLED=true` and no collector hangs the suite forever.
- Never run `./check.sh` and `./run_tests.sh` concurrently; each spawns ~189 parallel pytest workers.
- Do not `git push`. Commit locally only.
- Comments: one line maximum, only for non-obvious "why".

---

## File Structure

**Backend — create:**
- `backend/app/services/node_execution/nodes/html_output_mapper_node.py` — renders the template, returns the structured output. Nothing else.
- `backend/app/services/html_response.py` — two pure functions deciding whether a run answers with HTML. No DB, no FastAPI request handling.
- `backend/app/services/agent_tool_policy.py` — the one list of node types that may never become an agent tool.
- `backend/alembic/versions/114_add_workflow_http_method.py`
- `backend/tests/test_html_output_mapper_node.py`
- `backend/tests/test_html_response_api.py`
- `backend/tests/test_workflow_http_method.py`
- `backend/tests/test_agent_tool_policy.py`

**Backend — modify:**
- `backend/app/services/node_execution/registry.py` — one registry line.
- `backend/app/services/workflow_executor.py` — terminal-type constants, tool-schema guard.
- `backend/app/services/highlight/highlight_builder.py` — one set entry.
- `backend/app/services/workflow_status.py` — the `web` verdict.
- `backend/app/db/models.py`, `backend/app/models/schemas.py` — the `http_method` column and fields.
- `backend/app/api/workflows.py` — route methods, 405 enforcement, HTML return, status call sites.
- `backend/app/services/workflow_dsl_prompt.py` — DSL section 8c.
- `backend/tests/test_workflow_trigger_status.py` — the `web` cases.

**Frontend — create:**
- `frontend/src/components/Panels/propertiesPanel/nodes/HtmlOutputMapperNodeProperties.vue`
- `frontend/src/features/release-tour/components/visuals/HtmlOutputMapperTourVisual.vue`
- `frontend/src/docs/content/nodes/html-output-mapper-node.md`

**Frontend — modify:** `types/node.ts`, `types/workflow.ts`, `lib/nodeIcons.ts`, `lib/canvasConnectionRules.ts`, `lib/workflowEdges.ts`, `lib/workflowPreview.ts`, `components/Nodes/BaseNode.vue`, `components/Panels/NodePanel.vue`, `components/Panels/propertiesPanel/usePropertiesPanelController.ts`, `components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`, `components/Workflows/WorkflowStatusBadge.vue`, `components/Workflows/WorkflowStatusFilter.vue`, `views/EditorView.vue`, `docs/manifest.ts`, `docs/content/reference/features.md`, `docs/content/reference/node-types.md`, `docs/content/reference/webhooks.md`, `docs/content/tabs/workflows-tab.md`, `features/release-tour/releaseRegistry.ts`, `features/release-tour/tourVisuals.ts`, `e2e/support.ts`.

---

## Task 1: The node handler

**Files:**
- Create: `backend/app/services/node_execution/nodes/html_output_mapper_node.py`
- Modify: `backend/app/services/node_execution/registry.py`
- Test: `backend/tests/test_html_output_mapper_node.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_html_output_mapper_node.py`:

```python
"""HTML output mapper: template rendering, defaults, and structured node output."""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


def _run(nodes: list[dict], edges: list[dict], body: dict) -> dict:
    ex = WorkflowExecutor(nodes=nodes, edges=edges)
    result = ex.execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {}, "query": {}, "body": body},
    )
    assert result.status == "success", result.node_results
    return {r["node_id"]: r["output"] for r in result.node_results}


class HtmlOutputMapperNodeTests(unittest.TestCase):
    def _nodes(self, data: dict) -> list[dict]:
        return [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {"id": "html1", "type": "htmlOutputMapper", "data": data},
        ]

    EDGES = [{"id": "e1", "source": "in1", "target": "html1"}]

    def test_interpolates_expressions_into_the_body(self) -> None:
        nodes = self._nodes(
            {"label": "page", "html": "<h1>$userInput.text</h1>"},
        )
        outputs = _run(nodes, self.EDGES, {"text": "Hello"})
        self.assertEqual(outputs["html1"]["html"], "<h1>Hello</h1>")

    def test_resolves_several_spans_in_one_body(self) -> None:
        nodes = self._nodes(
            {
                "label": "page",
                "html": "<title>$userInput.text</title><p>$userInput.text!</p>",
            },
        )
        outputs = _run(nodes, self.EDGES, {"text": "Hi"})
        self.assertEqual(outputs["html1"]["html"], "<title>Hi</title><p>Hi!</p>")

    def test_defaults_status_and_content_type(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>ok</p>"})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 200)
        self.assertEqual(outputs["html1"]["contentType"], "text/html; charset=utf-8")

    def test_honours_configured_status_and_content_type(self) -> None:
        nodes = self._nodes(
            {
                "label": "page",
                "html": "<p>gone</p>",
                "statusCode": 404,
                "contentType": "text/plain; charset=utf-8",
            },
        )
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 404)
        self.assertEqual(outputs["html1"]["contentType"], "text/plain; charset=utf-8")

    def test_status_code_arrives_as_int_when_stored_as_string(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>x</p>", "statusCode": "201"})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 201)

    def test_out_of_range_status_falls_back_to_200(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>x</p>", "statusCode": 99})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 200)

    def test_blank_template_renders_empty_not_the_inputs_dict(self) -> None:
        nodes = self._nodes({"label": "page", "html": ""})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["html"], "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_output_mapper_node.py -v
```

Expected: every test FAILS. The registry has no `htmlOutputMapper` entry, so `execute_node_handler` falls through to `{"passthrough": ctx.inputs}` and `outputs["html1"]["html"]` raises `KeyError`.

- [ ] **Step 3: Write the handler**

Create `backend/app/services/node_execution/nodes/html_output_mapper_node.py`:

```python
from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext

DEFAULT_CONTENT_TYPE = "text/html; charset=utf-8"


def _coerce_status_code(raw: object) -> int:
    """HTTP status codes outside 100-599 would make Starlette raise mid-response."""
    try:
        code = int(str(raw).strip())
    except (TypeError, ValueError):
        return 200
    if code < 100 or code > 599:
        return 200
    return code


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the htmlOutputMapper node."""
    self = ctx.executor
    node_data = ctx.node_data

    template = str(node_data.get("html") or "")
    html = self.evaluate_nonempty_message_template(template, ctx.inputs, ctx.node_id)

    content_type = str(node_data.get("contentType") or "").strip() or DEFAULT_CONTENT_TYPE

    return {
        "html": html,
        "statusCode": _coerce_status_code(node_data.get("statusCode")),
        "contentType": content_type,
    }
```

- [ ] **Step 4: Register the handler**

In `backend/app/services/node_execution/registry.py`, find these two lines in
`_HANDLER_MODULES`:

```python
    "http": "http_node",
    "imapTrigger": "imap_trigger_node",
```

Replace them with:

```python
    "htmlOutputMapper": "html_output_mapper_node",
    "http": "http_node",
    "imapTrigger": "imap_trigger_node",
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_output_mapper_node.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/node_execution/nodes/html_output_mapper_node.py \
        backend/app/services/node_execution/registry.py \
        backend/tests/test_html_output_mapper_node.py
git commit -m "Add htmlOutputMapper node handler"
```

---

## Task 2: Teach the executor that htmlOutputMapper is a terminal

Without this the node is a plain leaf: it does not emit a `final_output` event, it is not
highlighted on the canvas as an output, and edges leaving it are still traversed.

**Files:**
- Modify: `backend/app/services/workflow_executor.py:2572-2589`, `:2591-2620`, `:9408`
- Modify: `backend/app/services/highlight/highlight_builder.py:15`
- Test: `backend/tests/test_html_output_mapper_node.py`

- [ ] **Step 1: Write the failing test**

Append to the `HtmlOutputMapperNodeTests` class in `backend/tests/test_html_output_mapper_node.py`:

```python
    def test_counts_as_an_output_node_not_merely_a_leaf(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>$userInput.text</p>"})
        ex = WorkflowExecutor(nodes=nodes, edges=self.EDGES)
        ex.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
        )
        self.assertIn("html1", ex.get_output_nodes())

    def test_downstream_edges_are_not_traversed(self) -> None:
        nodes = [
            *self._nodes({"label": "page", "html": "<p>x</p>"}),
            {"id": "after", "type": "consoleLog", "data": {"label": "after"}},
        ]
        edges = [*self.EDGES, {"id": "e2", "source": "html1", "target": "after"}]
        ex = WorkflowExecutor(nodes=nodes, edges=edges)
        result = ex.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
        )
        ran = {r["node_id"] for r in result.node_results}
        self.assertNotIn("after", ran)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_output_mapper_node.py -v -k "output_node or downstream"
```

Expected: both FAIL. `test_counts_as_an_output_node_not_merely_a_leaf` may accidentally pass
because `html1` is also a leaf — if it does, that is fine, keep it as a regression guard.
`test_downstream_edges_are_not_traversed` FAILS with `after` present in `ran`.

- [ ] **Step 3: Introduce the shared terminal-type constants**

In `backend/app/services/workflow_executor.py`, add these module-level constants immediately
above the `def unwrap_single_json_output_terminal_outputs(` definition (currently line 1800):

```python
#: Terminal mappers: sinks whose output replaces the wrapped per-label response shape.
TERMINAL_MAPPER_NODE_TYPES: frozenset[str] = frozenset({"jsonOutputMapper", "htmlOutputMapper"})

#: Every node type that terminates a branch and contributes the workflow's final output.
OUTPUT_TERMINAL_NODE_TYPES: frozenset[str] = frozenset({"output", *TERMINAL_MAPPER_NODE_TYPES})
```

- [ ] **Step 4: Use them at the three existing branch points**

In `get_output_nodes` (line 2578), find:

```python
            if node.get("type") in ("output", "jsonOutputMapper")
```

Replace with:

```python
            if node.get("type") in OUTPUT_TERMINAL_NODE_TYPES
```

In `get_active_edges` (line 2613), find:

```python
            if source_node.get("type") == "jsonOutputMapper":
                continue
```

Replace with:

```python
            if source_node.get("type") in TERMINAL_MAPPER_NODE_TYPES:
                continue
```

At line 9408, find:

```python
        if node_type in ("output", "jsonOutputMapper") and result.status == "success":
```

Replace with:

```python
        if node_type in OUTPUT_TERMINAL_NODE_TYPES and result.status == "success":
```

At line 9823, find:

```python
            is_json_mapper_final = node_for_final.get("type") == "jsonOutputMapper"
```

Replace with:

```python
            is_json_mapper_final = node_for_final.get("type") in TERMINAL_MAPPER_NODE_TYPES
```

- [ ] **Step 5: Add the node to the canvas highlight set**

In `backend/app/services/highlight/highlight_builder.py` line 15, find:

```python
OUTPUT_NODE_TYPES = {"output", "jsonOutputMapper", "chartOutput"}
```

Replace with:

```python
OUTPUT_NODE_TYPES = {"output", "jsonOutputMapper", "htmlOutputMapper", "chartOutput"}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_output_mapper_node.py tests/test_json_output_mapper_node.py -v
```

Expected: all pass. `test_json_output_mapper_node.py` must stay green — the constants are a
pure refactor of the tuples it already relied on.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/workflow_executor.py \
        backend/app/services/highlight/highlight_builder.py \
        backend/tests/test_html_output_mapper_node.py
git commit -m "Treat htmlOutputMapper as an output terminal in the executor"
```

---

## Task 3: Decide when a run answers with HTML

**Files:**
- Create: `backend/app/services/html_response.py`
- Test: `backend/tests/test_html_response_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_html_response_api.py`:

```python
"""Deciding when a workflow run answers with text/html instead of JSON."""

import unittest

from app.services.html_response import build_html_response, find_sole_html_terminal


def _html_node(node_id: str = "html1") -> dict:
    return {"id": node_id, "type": "htmlOutputMapper", "data": {"label": "page"}}


class FindSoleHtmlTerminalTests(unittest.TestCase):
    def test_finds_the_only_terminal(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, _html_node()]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")

    def test_none_when_there_is_no_html_node(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}]
        self.assertIsNone(find_sole_html_terminal(nodes, []))

    def test_none_when_a_second_terminal_exists(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "out1", "type": "output", "data": {"label": "out"}},
        ]
        edges = [{"source": "in1", "target": "html1"}, {"source": "in1", "target": "out1"}]
        self.assertIsNone(find_sole_html_terminal(nodes, edges))

    def test_none_when_the_html_node_is_deactivated(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            {"id": "html1", "type": "htmlOutputMapper", "data": {"active": False}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertIsNone(find_sole_html_terminal(nodes, edges))

    def test_sticky_notes_do_not_count_as_a_second_terminal(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "note", "type": "sticky", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")

    def test_error_handlers_do_not_count_as_a_second_terminal(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "err", "type": "errorHandler", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")


class BuildHtmlResponseTests(unittest.TestCase):
    def test_builds_a_response_from_the_node_result(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "success",
                "output": {
                    "html": "<h1>hi</h1>",
                    "statusCode": 201,
                    "contentType": "text/html; charset=utf-8",
                },
            }
        ]
        response = build_html_response(node_results, "html1")
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.body, b"<h1>hi</h1>")
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")

    def test_none_when_the_node_did_not_run(self) -> None:
        self.assertIsNone(build_html_response([], "html1"))

    def test_none_when_the_node_errored(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "error",
                "output": {},
            }
        ]
        self.assertIsNone(build_html_response(node_results, "html1"))

    def test_none_when_the_output_is_not_the_expected_shape(self) -> None:
        node_results = [
            {"node_id": "html1", "node_type": "htmlOutputMapper", "status": "success", "output": "x"}
        ]
        self.assertIsNone(build_html_response(node_results, "html1"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_response_api.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'app.services.html_response'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/html_response.py`:

```python
"""Decide whether a workflow run answers with an HTML page instead of a JSON body.

Both functions are pure: the API layer owns the request, the DB session, and the
`X-Simple-Response` decision. This module only reads the graph and the node results.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import HTMLResponse

HTML_MAPPER_NODE_TYPE = "htmlOutputMapper"

#: Never counted when deciding whether a terminal is the *sole* terminal.
_NON_TERMINAL_TYPES = frozenset({"sticky", "errorHandler"})


def _is_active(node: dict[str, Any]) -> bool:
    data = node.get("data")
    if not isinstance(data, dict):
        return True
    return data.get("active") is not False


def find_sole_html_terminal(
    nodes: list[Any] | None,
    edges: list[Any] | None,
) -> str | None:
    """The node id when the only active terminal is an htmlOutputMapper, else None.

    Mirrors ``extract_output_node_from_workflow``'s notion of a terminal: a node no active
    edge leaves, ignoring sticky notes and error handlers.
    """
    node_list = [n for n in nodes or [] if isinstance(n, dict)]
    source_ids = {
        e.get("source") for e in edges or [] if isinstance(e, dict) and e.get("source")
    }

    terminals = [
        n
        for n in node_list
        if n.get("id") not in source_ids
        and _is_active(n)
        and n.get("type") not in _NON_TERMINAL_TYPES
    ]
    if len(terminals) != 1:
        return None

    sole = terminals[0]
    if sole.get("type") != HTML_MAPPER_NODE_TYPE:
        return None
    node_id = sole.get("id")
    return str(node_id) if node_id else None


def build_html_response(
    node_results: list[Any] | None,
    node_id: str,
) -> HTMLResponse | None:
    """Turn the html node's structured output into a response, or None if it produced none."""
    for row in node_results or []:
        if not isinstance(row, dict) or row.get("node_id") != node_id:
            continue
        if row.get("status") != "success":
            return None
        output = row.get("output")
        if not isinstance(output, dict) or "html" not in output:
            return None
        status_code = output.get("statusCode")
        return HTMLResponse(
            content=str(output.get("html") or ""),
            status_code=status_code if isinstance(status_code, int) else 200,
            media_type=str(output.get("contentType") or "text/html; charset=utf-8"),
        )
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_response_api.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/html_response.py backend/tests/test_html_response_api.py
git commit -m "Add html_response helpers for sole-terminal HTML runs"
```

---

## Task 4: Return HTML from /execute

**Files:**
- Modify: `backend/app/api/workflows.py` (imports; the `simple_response` returns at ~2915, ~3069)
- Test: `backend/tests/test_html_response_api.py`

The existing execution API tests call `execute_workflow_endpoint` **directly** with an
`AsyncMock` db and patch `asyncio.to_thread` to return a canned `ExecutionResult` — there is
no HTTP client fixture. Follow that pattern exactly; see
`backend/tests/test_workflow_execution_api.py:1853-1926` for the original.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_html_response_api.py`. Add these imports at the top of the file:

```python
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.api.workflows import execute_workflow_endpoint
from app.services.html_response import build_html_response, find_sole_html_terminal
from app.services.workflow_executor import ExecutionResult
```

Then append:

```python
class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def make_request(
    *,
    method: str = "POST",
    body: bytes = b"",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": "/api/workflows/test/execute",
        "headers": headers or [],
        "query_string": query_string,
    }
    return Request(scope, receive)


HTML_NODE = {
    "id": "html1",
    "type": "htmlOutputMapper",
    "data": {"label": "page", "html": "<h1>Hello Ada</h1>"},
}
INPUT_NODE = {
    "id": "in1",
    "type": "textInput",
    "data": {"label": "userInput", "inputFields": [{"key": "name"}]},
}


class ExecuteReturnsHtmlTests(unittest.IsolatedAsyncioTestCase):
    """The route-level contract: sole html terminal + simple response == text/html."""

    def _workflow(self, nodes: list[dict], edges: list[dict]) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method="POST",
            name="Page Workflow",
        )

    def _result(self, workflow_id: uuid.UUID, node_output: dict) -> ExecutionResult:
        return ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"page": node_output},
            node_results=[
                {
                    "node_id": "html1",
                    "node_label": "page",
                    "node_type": "htmlOutputMapper",
                    "status": "success",
                    "output": node_output,
                    "execution_time_ms": 1.0,
                    "error": None,
                }
            ],
            execution_time_ms=10.0,
        )

    async def _call(
        self,
        *,
        nodes: list[dict],
        edges: list[dict],
        node_output: dict,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> object:
        workflow = self._workflow(nodes, edges)
        execution_result = self._result(workflow.id, node_output)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.workflows.ExecutionHistory", side_effect=lambda **kw: SimpleNamespace(id=uuid.uuid4())),
        ):
            return await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(body=b"{}", headers=headers),
                current_user=None,
                db=db,
            )

    OUTPUT = {
        "html": "<h1>Hello Ada</h1>",
        "statusCode": 200,
        "contentType": "text/html; charset=utf-8",
    }
    EDGES = [{"id": "e1", "source": "in1", "target": "html1"}]

    async def test_sole_html_terminal_returns_text_html(self) -> None:
        response = await self._call(
            nodes=[INPUT_NODE, HTML_NODE], edges=self.EDGES, node_output=self.OUTPUT
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertEqual(response.body, b"<h1>Hello Ada</h1>")

    async def test_simple_response_false_still_returns_the_json_envelope(self) -> None:
        response = await self._call(
            nodes=[INPUT_NODE, HTML_NODE],
            edges=self.EDGES,
            node_output=self.OUTPUT,
            headers=[(b"x-simple-response", b"false")],
        )
        # The non-simple path returns the pydantic model, not a Response.
        self.assertTrue(hasattr(response, "node_results"))

    async def test_a_second_terminal_keeps_json(self) -> None:
        nodes = [
            INPUT_NODE,
            HTML_NODE,
            {"id": "out1", "type": "output", "data": {"label": "out", "message": "done"}},
        ]
        edges = [*self.EDGES, {"id": "e2", "source": "in1", "target": "out1"}]
        response = await self._call(nodes=nodes, edges=edges, node_output=self.OUTPUT)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))

    async def test_configured_status_code_reaches_the_response(self) -> None:
        output = {
            "html": "<p>nope</p>",
            "statusCode": 404,
            "contentType": "text/html; charset=utf-8",
        }
        response = await self._call(
            nodes=[INPUT_NODE, HTML_NODE], edges=self.EDGES, node_output=output
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.body, b"<p>nope</p>")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_response_api.py::ExecuteReturnsHtmlTests -v
```

Expected: `test_sole_html_terminal_returns_text_html` FAILS — content-type is
`application/json` and the body is `{"page": {"html": "<h1>Hello Ada</h1>", ...}}`.

- [ ] **Step 3: Import the helpers**

In `backend/app/api/workflows.py`, add to the existing `app.services` import block:

```python
from app.services.html_response import build_html_response, find_sole_html_terminal
```

Confirm `HTMLResponse` is importable — if `from fastapi.responses import JSONResponse` is
already present, extend it to `from fastapi.responses import HTMLResponse, JSONResponse`.
`build_html_response` returns the `HTMLResponse` itself, so a direct import may prove
unnecessary; drop it if ruff flags it as unused.

- [ ] **Step 4: Return HTML at the two simple-response exits**

Directly above the final `if simple_response:` in `execute_workflow_endpoint` (currently
line 3069, the one immediately preceding `return WorkflowExecuteResponse(` at the end of the
function), insert:

```python
    if simple_response:
        html_node_id = find_sole_html_terminal(workflow.nodes, workflow.edges)
        if html_node_id:
            html_response = build_html_response(execution_result.node_results, html_node_id)
            if html_response is not None:
                return html_response
```

Apply the identical block above the `if simple_response:` inside the
`allow_downstream_pending` branch (currently line 2990), but return
`HTMLResponse(...)` with the background tasks attached:

```python
            if simple_response:
                html_node_id = find_sole_html_terminal(workflow.nodes, workflow.edges)
                if html_node_id:
                    html_response = build_html_response(
                        execution_result.node_results, html_node_id
                    )
                    if html_response is not None:
                        html_response.background = background_tasks
                        await db.commit()
                        return html_response
```

Leave the cached-response exit (line 2764), the file-upload mint exit (line 2807), and the
`throwError` custom-status exit (line 2990's sibling at ~3051) on JSON. A cached body, a
mint payload, and a thrown error are not the html node's output.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_html_response_api.py tests/test_workflow_execution_api.py -v
```

Expected: all pass, including the pre-existing execution API tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/workflows.py backend/tests/test_html_response_api.py
git commit -m "Return text/html from /execute when the sole terminal is htmlOutputMapper"
```

---

## Task 5: The http_method column

**Files:**
- Create: `backend/alembic/versions/114_add_workflow_http_method.py`
- Modify: `backend/app/db/models.py:308`, `backend/app/models/schemas.py:231`, `:277`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/114_add_workflow_http_method.py`:

```python
"""add workflow http method

Revision ID: 114_add_workflow_http_method
Revises: 113_add_folder_description
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "114_add_workflow_http_method"
down_revision: str | None = "113_add_folder_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default is what keeps every existing workflow answering POST exactly as before.
    op.add_column(
        "workflows",
        sa.Column("http_method", sa.String(8), nullable=False, server_default="POST"),
    )


def downgrade() -> None:
    op.drop_column("workflows", "http_method")
```

- [ ] **Step 2: Add the column to the model**

In `backend/app/db/models.py`, find line 308:

```python
    sse_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

Insert directly above it:

```python
    http_method: Mapped[str] = mapped_column(
        String(8), default="POST", server_default="POST", nullable=False
    )
```

- [ ] **Step 3: Add the schema fields**

In `backend/app/models/schemas.py`, find line 231 (`sse_enabled: bool | None = None`, inside
the update model) and insert directly above it:

```python
    http_method: str | None = None
```

Find line 277 (`sse_enabled: bool = False`, inside the response model) and insert directly
above it:

```python
    http_method: str = "POST"
```

- [ ] **Step 4: Verify the migration applies**

```bash
docker-compose up -d postgres
cd backend && uv run alembic upgrade head && uv run alembic current
```

Expected: `114_add_workflow_http_method (head)`.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/114_add_workflow_http_method.py \
        backend/app/db/models.py backend/app/models/schemas.py
git commit -m "Add workflows.http_method column defaulting to POST"
```

---

## Task 6: Enforce the method on /execute

**Files:**
- Modify: `backend/app/api/workflows.py:2664`, `:3303`
- Test: `backend/tests/test_workflow_http_method.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_http_method.py`, reusing the direct-call harness from
`tests/test_html_response_api.py` (Task 4):

```python
"""Per-workflow HTTP method: enforcement, defaults, and the test_run exemption."""

import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from app.api.workflows import execute_workflow_endpoint
from app.services.workflow_executor import ExecutionResult


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def make_request(*, method: str, query_string: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": "/api/workflows/test/execute",
        "headers": [],
        "query_string": query_string,
    }
    return Request(scope, receive)


class WorkflowHttpMethodTests(unittest.IsolatedAsyncioTestCase):
    NODES = [
        {"id": "in1", "type": "textInput", "data": {"label": "userInput", "inputFields": [{"key": "text"}]}},
        {"id": "out1", "type": "output", "data": {"label": "out", "message": "ok"}},
    ]
    EDGES = [{"id": "e1", "source": "in1", "target": "out1"}]

    def _workflow(self, http_method: str = "POST") -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=self.NODES,
            edges=self.EDGES,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method=http_method,
            name="Method Workflow",
        )

    async def _call(self, workflow: SimpleNamespace, method: str, query: bytes = b"") -> object:
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"out": {"result": "ok"}},
            node_results=[],
            execution_time_ms=5.0,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.workflows.ExecutionHistory", side_effect=lambda **kw: SimpleNamespace(id=uuid.uuid4())),
        ):
            return await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(method=method, query_string=query),
                current_user=None,
                db=db,
            )

    async def test_defaults_to_post_and_post_succeeds(self) -> None:
        response = await self._call(self._workflow(), "POST")
        self.assertEqual(response.status_code, 200)

    async def test_wrong_method_is_rejected_with_405_and_allow(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._workflow("GET"), "POST")
        self.assertEqual(ctx.exception.status_code, 405)
        self.assertEqual(ctx.exception.headers["Allow"], "GET")

    async def test_each_configured_method_succeeds(self) -> None:
        for method in ("GET", "POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                response = await self._call(self._workflow(method), method)
                self.assertEqual(response.status_code, 200)

    async def test_test_run_bypasses_enforcement(self) -> None:
        """The editor's Run button must keep working whatever the dropdown says."""
        response = await self._call(self._workflow("GET"), "POST", query=b"test_run=true")
        self.assertEqual(response.status_code, 200)

    async def test_a_missing_column_value_is_treated_as_post(self) -> None:
        """Rows predating the migration must behave exactly as they do today."""
        workflow = self._workflow()
        workflow.http_method = None
        response = await self._call(workflow, "POST")
        self.assertEqual(response.status_code, 200)



class ExecuteRouteMethodsTests(unittest.TestCase):
    """The tests above call the endpoint directly, so they never touch the router.

    Without this case, opening the route to four verbs could be forgotten entirely and every
    enforcement test would still pass.
    """

    def _methods_for(self, path_suffix: str) -> set[str]:
        from app.api.workflows import router

        for route in router.routes:
            if getattr(route, "path", "") == path_suffix:
                return {m for m in route.methods if m not in ("HEAD", "OPTIONS")}
        raise AssertionError(f"route {path_suffix} not registered")

    def test_execute_accepts_all_four_verbs(self) -> None:
        self.assertEqual(
            self._methods_for("/{workflow_id}/execute"),
            {"GET", "POST", "PUT", "DELETE"},
        )

    def test_execute_stream_accepts_all_four_verbs(self) -> None:
        self.assertEqual(
            self._methods_for("/{workflow_id}/execute/stream"),
            {"GET", "POST", "PUT", "DELETE"},
        )


if __name__ == "__main__":
    unittest.main()
```

Note: `WorkflowHttpMethodTests` asserts on `HTTPException` rather than a 405 response body,
because it calls the endpoint function directly rather than through the ASGI stack. That is
also why `ExecuteRouteMethodsTests` exists — it is the only case that fails if the
`@router.api_route` change in Step 3 is skipped.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_workflow_http_method.py -v
```

Expected two specific failures:

- `test_wrong_method_is_rejected_with_405_and_allow` FAILS — no `HTTPException` is raised at
  all, because nothing enforces the method yet.
- Both `ExecuteRouteMethodsTests` cases FAIL — the routes are registered for `POST` only.

The remaining cases pass already, since a direct function call bypasses the router. That is
expected; they stay as regression guards.

- [ ] **Step 3: Open the route to all four methods**

In `backend/app/api/workflows.py` line 2664, find:

```python
@router.post("/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
```

Replace with:

```python
@router.api_route(
    "/{workflow_id}/execute",
    methods=["GET", "POST", "PUT", "DELETE"],
    response_model=WorkflowExecuteResponse,
)
```

At line 3303, find:

```python
@router.post("/{workflow_id}/execute/stream")
```

Replace with:

```python
@router.api_route("/{workflow_id}/execute/stream", methods=["GET", "POST", "PUT", "DELETE"])
```

- [ ] **Step 4: Add the enforcement helper**

In `backend/app/api/workflows.py`, immediately after the `parse_execute_body` function
(ending line 2661), add:

```python
def enforce_workflow_http_method(workflow: Workflow, request: Request, test_run: bool) -> None:
    """Reject a verb the workflow is not configured for.

    ``test_run`` requests are exempt: the editor's Run button and the debug panel always POST,
    and a workflow set to GET would otherwise be untestable from inside the product.
    """
    if test_run:
        return
    configured = (getattr(workflow, "http_method", None) or "POST").upper()
    if request.method.upper() != configured:
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail=f"This workflow accepts {configured} requests only",
            headers={"Allow": configured},
        )
```

- [ ] **Step 5: Call it from both endpoints**

In `execute_workflow_endpoint`, directly after the `await validate_workflow_auth(...)` call
(line ~2686), insert:

```python
    enforce_workflow_http_method(workflow, request, test_run)
```

Do the same in the stream endpoint, after its own `validate_workflow_auth` call.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_workflow_http_method.py tests/test_workflow_execution_api.py \
  tests/test_stream_execution_disconnect.py -v
```

Expected: all pass. The two pre-existing suites POST against workflows whose `http_method`
defaults to `POST`, so they are unaffected.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/workflows.py backend/tests/test_workflow_http_method.py
git commit -m "Accept and enforce GET/POST/PUT/DELETE on workflow execute"
```

---

## Task 7: The WEB status

**Files:**
- Modify: `backend/app/services/workflow_status.py`
- Modify: `backend/app/api/workflows.py` (every `compute_trigger_status(` call site)
- Test: `backend/tests/test_workflow_trigger_status.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflow_trigger_status.py`:

```python
class WebStatusTests(unittest.TestCase):
    HTML_NODE = {"id": "html1", "type": "htmlOutputMapper", "data": {"label": "page"}}

    def test_sole_html_terminal_reads_web_instead_of_manual(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, self.HTML_NODE]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(compute_trigger_status(nodes, edges), "web")

    def test_web_survives_the_api_refinement(self) -> None:
        """A page-serving workflow reads WEB, not API, after its first HTTP call."""
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, self.HTML_NODE]
        edges = [{"source": "in1", "target": "html1"}]
        status = compute_trigger_status(nodes, edges)
        self.assertEqual(refine_manual_status(status, "api"), "web")

    def test_a_cron_trigger_still_wins(self) -> None:
        nodes = [
            {"id": "c1", "type": "cron", "data": {"cronExpression": "* * * * *"}},
            self.HTML_NODE,
        ]
        edges = [{"source": "c1", "target": "html1"}]
        self.assertEqual(compute_trigger_status(nodes, edges), "scheduled")

    def test_a_second_terminal_keeps_manual(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            self.HTML_NODE,
            {"id": "out1", "type": "output", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}, {"source": "in1", "target": "out1"}]
        self.assertEqual(compute_trigger_status(nodes, edges), "manual")

    def test_edges_omitted_keeps_the_old_manual_behaviour(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}]
        self.assertEqual(compute_trigger_status(nodes), "manual")
```

Add `refine_manual_status` to that file's existing import from
`app.services.workflow_status` if it is not already imported.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_workflow_trigger_status.py -v
```

Expected: the new cases FAIL — `compute_trigger_status` takes one argument and never returns
`"web"`.

- [ ] **Step 3: Add the web verdict**

In `backend/app/services/workflow_status.py`, add `"web"` to the `TriggerStatus` literal:

```python
TriggerStatus = Literal[
    "scheduled",
    "listening",
    "paused",
    "manual",
    "api",
    "subWorkflow",
    "portal",
    "web",
]
```

Add the import at the top of the file, after the `typing` import:

```python
from app.services.html_response import find_sole_html_terminal
```

Change the signature and the `manual` return of `compute_trigger_status`:

```python
def compute_trigger_status(
    nodes: list[Any] | None,
    edges: list[Any] | None = None,
) -> TriggerStatus:
    """Classify how a workflow starts.

    ``scheduled`` an active cron node exists, ``listening`` an active event trigger exists,
    ``paused`` trigger nodes exist but every one is deactivated, ``web`` no trigger nodes and
    the sole terminal serves an HTML page, ``manual`` no trigger nodes.
    """
    trigger_nodes = [
        node
        for node in nodes or []
        if isinstance(node, dict) and node.get("type") in TRIGGER_NODE_TYPES
    ]
    if not trigger_nodes:
        # Decided from the graph, so it short-circuits refine_manual_status: a page-serving
        # workflow should read WEB rather than API after its first HTTP call.
        if find_sole_html_terminal(nodes, edges):
            return "web"
        return "manual"
```

Leave the rest of the function and `refine_manual_status` untouched — the latter already
returns any non-`manual` status unchanged.

Update the module docstring's closing paragraph to mention the new verdict:

```python
A workflow with no trigger node is only "manual" until something calls it, unless its sole
terminal is an ``htmlOutputMapper`` - then it serves a page and reads "web". When the last run
came in over the HTTP API, from a parent workflow, or from the portal, the chip says so
instead - see ``refine_manual_status``.
```

- [ ] **Step 4: Pass edges at every call site**

```bash
grep -n "compute_trigger_status(" backend/app/api/*.py
```

For each hit of the form `compute_trigger_status(w.nodes)`, change it to
`compute_trigger_status(w.nodes, w.edges)`. Where the variable is named differently
(`workflow.nodes`, `wf.nodes`), use that object's `.edges` accordingly.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_workflow_trigger_status.py -v
```

Expected: all pass, existing cases included.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_status.py backend/app/api/ \
        backend/tests/test_workflow_trigger_status.py
git commit -m "Report web status for workflows whose sole terminal serves HTML"
```

---

## Task 8: Terminal mappers cannot be agent tools

`WorkflowExecutor._build_node_tool_schemas` has no block list at all today, so every workflow
already saved with a mapper on a `tool-input` edge keeps offering it. This is the retroactive
half of the requirement — the frontend change in Task 12 only stops *new* connections.

**Files:**
- Create: `backend/app/services/agent_tool_policy.py`
- Modify: `backend/app/services/workflow_executor.py:4841-4886`
- Test: `backend/tests/test_agent_tool_policy.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_agent_tool_policy.py`:

```python
"""Terminal mappers must never be offered to an agent as callable tools."""

import unittest

from app.services.workflow_executor import WorkflowExecutor


class AgentToolPolicyTests(unittest.TestCase):
    def _executor(self, tool_node: dict) -> WorkflowExecutor:
        nodes = [
            {"id": "agent1", "type": "agent", "data": {"label": "assistant"}},
            tool_node,
        ]
        edges = [
            {
                "id": "t1",
                "source": tool_node["id"],
                "target": "agent1",
                "targetHandle": "tool-input",
            }
        ]
        return WorkflowExecutor(nodes=nodes, edges=edges)

    def test_json_output_mapper_is_not_offered_as_a_tool(self) -> None:
        ex = self._executor(
            {"id": "map1", "type": "jsonOutputMapper", "data": {"label": "payload"}}
        )
        self.assertEqual(ex._build_node_tool_schemas("agent1"), [])

    def test_html_output_mapper_is_not_offered_as_a_tool(self) -> None:
        ex = self._executor(
            {"id": "html1", "type": "htmlOutputMapper", "data": {"label": "page"}}
        )
        self.assertEqual(ex._build_node_tool_schemas("agent1"), [])

    def test_an_ordinary_node_is_still_offered(self) -> None:
        ex = self._executor({"id": "http1", "type": "http", "data": {"label": "fetch"}})
        schemas = ex._build_node_tool_schemas("agent1")
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["_node_id"], "http1")

    def test_the_output_node_is_deliberately_still_allowed(self) -> None:
        """Only the two mappers are blocked - narrowing further would break saved workflows."""
        ex = self._executor({"id": "out1", "type": "output", "data": {"label": "reply"}})
        self.assertEqual(len(ex._build_node_tool_schemas("agent1")), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_agent_tool_policy.py -v
```

Expected: the two mapper tests FAIL — each returns one schema instead of none.

- [ ] **Step 3: Write the policy module**

Create `backend/app/services/agent_tool_policy.py`:

```python
"""Node types that may never become an agent tool.

Mirrors the frontend's ``BLOCKED_AS_TOOL_NODE_TYPES`` in
``frontend/src/lib/canvasConnectionRules.ts``. The canvas rule stops new connections; this
one covers workflows already saved with such an edge.
"""

from __future__ import annotations

#: Terminal mappers. Called mid-conversation they produce a response body nothing reads.
BLOCKED_AS_TOOL_NODE_TYPES: frozenset[str] = frozenset(
    {
        "jsonOutputMapper",
        "htmlOutputMapper",
    }
)


def is_blocked_as_tool(node_type: str | None) -> bool:
    """True when a node of this type must not be exposed to an agent as a tool."""
    return bool(node_type) and node_type in BLOCKED_AS_TOOL_NODE_TYPES
```

- [ ] **Step 4: Consult it in the tool-schema builder**

In `backend/app/services/workflow_executor.py`, add to the imports:

```python
from app.services.agent_tool_policy import is_blocked_as_tool
```

In `_build_node_tool_schemas` (line ~4852), find:

```python
        for node_id in tool_node_ids:
            node = self.nodes.get(node_id)
            if node is None:
                continue
            node_data = node.get("data", {})
```

Replace with:

```python
        for node_id in tool_node_ids:
            node = self.nodes.get(node_id)
            if node is None:
                continue
            if is_blocked_as_tool(node.get("type")):
                continue
            node_data = node.get("data", {})
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/test_agent_tool_policy.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Run the agent suites to check nothing relied on the old behaviour**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/ -k "agent or tool" -v
```

Expected: all pass. If a test asserts a `jsonOutputMapper` is a callable tool, that test
encodes the bug being fixed — update it and say so in the commit message.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent_tool_policy.py \
        backend/app/services/workflow_executor.py \
        backend/tests/test_agent_tool_policy.py
git commit -m "Stop offering terminal mappers to agents as tools"
```

---

## Task 9: Backend gate

- [ ] **Step 1: Format and lint**

```bash
cd backend && uv run ruff format . && uv run ruff check . --fix
```

Expected: "All checks passed".

- [ ] **Step 2: Run the whole backend suite**

```bash
cd backend && HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./run_tests.sh
```

Expected: all pass. Do not run this concurrently with `./check.sh`.

- [ ] **Step 3: Commit any formatting diff**

```bash
git add -A backend/
git commit -m "Apply ruff formatting" || echo "nothing to format"
```

---

## Task 10: The node on the canvas

**Files:**
- Modify: `frontend/src/types/workflow.ts:180`, `frontend/src/types/node.ts:404`
- Modify: `frontend/src/lib/nodeIcons.ts:73`, `:138`
- Modify: `frontend/src/components/Nodes/BaseNode.vue:48`, `:126`
- Modify: `frontend/src/components/Panels/NodePanel.vue:235`
- Modify: `frontend/src/lib/workflowEdges.ts:10`

- [ ] **Step 1: Add the node type to the union**

In `frontend/src/types/workflow.ts`, find line 180:

```typescript
  | "jsonOutputMapper"
```

Replace with:

```typescript
  | "jsonOutputMapper"
  | "htmlOutputMapper"
```

- [ ] **Step 2: Add the node definition**

In `frontend/src/types/node.ts`, find the closing brace of the `jsonOutputMapper` entry
(line 404, `  },` immediately before `  slack: {`) and insert the new entry after it:

```typescript
  htmlOutputMapper: {
    type: "htmlOutputMapper",
    label: "HTML output mapper",
    description:
      "Render an HTML page from a template; as the only terminal, the webhook responds with text/html instead of JSON",
    color: "node-output",
    icon: "FileCode2",
    inputs: 1,
    outputs: 0,
    defaultData: {
      label: "htmlResponse",
      html: "<!doctype html>\n<html>\n  <body>\n    <h1>$input.text</h1>\n  </body>\n</html>",
      statusCode: 200,
      contentType: "text/html; charset=utf-8",
    },
  },
```

- [ ] **Step 3: Register the icon and colour**

In `frontend/src/lib/nodeIcons.ts`, add `FileCode2` to the existing `lucide-vue-next` import,
then find line 73:

```typescript
  jsonOutputMapper: Braces,
```

Replace with:

```typescript
  jsonOutputMapper: Braces,
  htmlOutputMapper: FileCode2,
```

Find line 138:

```typescript
  jsonOutputMapper: "text-node-output",
```

Replace with:

```typescript
  jsonOutputMapper: "text-node-output",
  htmlOutputMapper: "text-node-output",
```

- [ ] **Step 4: Give it the output colour and suppress its output handle**

In `frontend/src/components/Nodes/BaseNode.vue`, find line 48:

```typescript
  jsonOutputMapper: "node-output",
```

Replace with:

```typescript
  jsonOutputMapper: "node-output",
  htmlOutputMapper: "node-output",
```

Find line 126:

```typescript
    && props.type !== "jsonOutputMapper"
```

Replace with:

```typescript
    && props.type !== "jsonOutputMapper"
    && props.type !== "htmlOutputMapper"
```

- [ ] **Step 5: Suppress the rendered source handle**

In `frontend/src/lib/workflowEdges.ts`, find line 10:

```typescript
  "jsonOutputMapper",
```

Replace with:

```typescript
  "jsonOutputMapper",
  "htmlOutputMapper",
```

- [ ] **Step 6: Hide it from dashboard-widget workflows**

In `frontend/src/components/Panels/NodePanel.vue`, find line 235:

```typescript
  "jsonOutputMapper",
```

Replace with:

```typescript
  "jsonOutputMapper",
  "htmlOutputMapper",
```

- [ ] **Step 7: Verify types compile**

```bash
cd frontend && bun run typecheck
```

Expected: PASS. If `NODE_DEFINITIONS` is typed as an exhaustive `Record<NodeType, …>`, adding
the union member without the definition would have errored — both edits land together, so it
should be clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/ frontend/src/lib/nodeIcons.ts frontend/src/lib/workflowEdges.ts \
        frontend/src/components/Nodes/BaseNode.vue frontend/src/components/Panels/NodePanel.vue
git commit -m "Add htmlOutputMapper node to the canvas palette"
```

---

## Task 11: The properties panel

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/HtmlOutputMapperNodeProperties.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue:94`

- [ ] **Step 1: Add the expression-field wiring to the controller**

In `usePropertiesPanelController.ts`, next to the `outputMessageInputRef` declaration
(line 473), add:

```typescript
  const htmlBodyInputRef = ref<ExpandableFieldRef | null>(null);
```

Add the doc slug at line 181, next to `jsonOutputMapper: "json-output-mapper-node",`:

```typescript
    htmlOutputMapper: "html-output-mapper-node",
```

Add the colour at line 118, next to `jsonOutputMapper: "node-output",`:

```typescript
    htmlOutputMapper: "node-output",
```

In `openPrimaryExpandDialogForSelectedNode` (line 2421), add a branch after the
`if (nodeType === "output") { … }` block:

```typescript
    } else if (nodeType === "htmlOutputMapper") {
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        if (htmlBodyInputRef.value) {
          nextTick(() => htmlBodyInputRef.value?.openExpandDialog());
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
```

In `selectedNodeHasPrimaryEvaluateExpandTarget` (line 3096), add `htmlOutputMapper` to the
group that returns `true` unconditionally:

```typescript
      case "set":
      case "jsonOutputMapper":
      case "htmlOutputMapper":
        return true;
```

Add `htmlBodyInputRef` to the object the composable returns, next to `outputMessageInputRef`
(line 9030):

```typescript
    htmlBodyInputRef,
```

- [ ] **Step 2: Create the properties component**

Create `frontend/src/components/Panels/propertiesPanel/nodes/HtmlOutputMapperNodeProperties.vue`:

```vue
<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  htmlBodyInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  updateNodeData,
} = usePropertiesPanelContext();

function updateStatusCode(raw: string): void {
  const parsed = Number.parseInt(raw, 10);
  updateNodeData("statusCode", Number.isNaN(parsed) ? 200 : parsed);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-2">
        <Label for="html-status-code">Status Code</Label>
        <Input
          id="html-status-code"
          type="number"
          :model-value="String(selectedNode.data.statusCode ?? 200)"
          placeholder="200"
          @update:model-value="updateStatusCode(String($event))"
        />
      </div>
      <div class="space-y-2">
        <Label for="html-content-type">Content Type</Label>
        <Input
          id="html-content-type"
          :model-value="String(selectedNode.data.contentType ?? '')"
          placeholder="text/html; charset=utf-8"
          @update:model-value="updateNodeData('contentType', $event)"
        />
      </div>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>HTML Body</Label>
      <ExpressionInput
        ref="htmlBodyInputRef"
        :model-value="selectedNode.data.html || ''"
        :placeholder="`<h1>${exampleRef}</h1>`"
        :rows="12"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="HTML body"
        field-key="html"
        @update:model-value="updateNodeData('html', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use $ prefix to interpolate values: {{ exampleRef }}. When this is the only terminal node,
        the workflow's webhook responds with this page instead of JSON.
      </p>
    </div>
  </template>
</template>
```

- [ ] **Step 3: Dispatch to it**

In `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`, add the
import alongside the other node property imports:

```typescript
import HtmlOutputMapperNodeProperties from "./HtmlOutputMapperNodeProperties.vue";
```

Find line 94:

```vue
  <SetJsonOutputMapperNodeProperties v-else-if="selectedNode?.type === 'set' || selectedNode?.type === 'jsonOutputMapper'" />
```

Insert directly after it:

```vue
  <HtmlOutputMapperNodeProperties v-else-if="selectedNode?.type === 'htmlOutputMapper'" />
```

- [ ] **Step 4: Verify**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/
git commit -m "Add htmlOutputMapper properties panel"
```

---

## Task 12: Block terminal mappers as agent tools (frontend)

**Files:**
- Modify: `frontend/src/lib/canvasConnectionRules.ts:9-27`

- [ ] **Step 1: Extend the block list**

In `frontend/src/lib/canvasConnectionRules.ts`, find:

```typescript
  "heymTrigger",
  "mcpCall",
]);
```

(the tail of `BLOCKED_AS_TOOL_NODE_TYPES`). Replace with:

```typescript
  "heymTrigger",
  "mcpCall",
  "jsonOutputMapper",
  "htmlOutputMapper",
]);
```

This list must stay in step with `backend/app/services/agent_tool_policy.py` from Task 8 — the
same two entries, no more. Do not add `output` or `chartOutput`: workflows may already use
them as tools, and silently breaking those is beyond this change.

- [ ] **Step 2: Verify**

```bash
cd frontend && bun run typecheck && bun run test
```

Expected: both PASS. Note that a bare `vitest run` fails 31 e2e files by design — use
`bun run test`, which scopes to `src/**/*.test.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/canvasConnectionRules.ts
git commit -m "Block terminal output nodes from agent tool connections"
```

---

## Task 13: The WEB chip (frontend)

**Files:**
- Modify: `frontend/src/types/workflow.ts:48-53`
- Modify: `frontend/src/components/Workflows/WorkflowStatusBadge.vue`
- Modify: `frontend/src/components/Workflows/WorkflowStatusFilter.vue:29-40`

- [ ] **Step 1: Extend the status union**

In `frontend/src/types/workflow.ts`, add `| "web"` to the end of the
`WorkflowTriggerStatus` union.

- [ ] **Step 2: Add the badge style**

In `frontend/src/components/Workflows/WorkflowStatusBadge.vue`, add to `STATUS_STYLES`,
directly after the `portal` entry:

```typescript
  web: {
    label: "WEB",
    badge: "bg-rose-500/10 text-rose-600 dark:text-rose-400 ring-rose-500/20",
    dot: "bg-rose-500",
    pulse: false,
  },
```

- [ ] **Step 3: Add the filter option**

In `frontend/src/components/Workflows/WorkflowStatusFilter.vue`, add to `OPTIONS`, directly
after the `portal` entry:

```typescript
  { value: "web", label: "WEB" },
```

- [ ] **Step 4: Verify**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: both PASS. `STATUS_STYLES` is typed `Record<WorkflowRowStatus, StatusStyle>`, so a
missing entry would have failed the typecheck.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/components/Workflows/
git commit -m "Show a WEB chip for page-serving workflows"
```

---

## Task 14: The method selector and both cURL snippets

**Files:**
- Modify: `frontend/src/types/workflow.ts` (the `Workflow` interface)
- Modify: `frontend/src/views/EditorView.vue:98`, `:879`, `:1032-1075`, `:2196-2212`
- Modify: `frontend/src/lib/workflowPreview.ts:174-205`
- Test: `frontend/src/lib/workflowPreview.test.ts`

- [ ] **Step 1: Add the field to the Workflow type**

In `frontend/src/types/workflow.ts`, add to the `Workflow` interface next to `sse_enabled`:

```typescript
  http_method?: string;
```

- [ ] **Step 2: Write the failing test**

Create or extend `frontend/src/lib/workflowPreview.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { Workflow } from "@/types/workflow";
import { buildWorkflowCurl } from "@/lib/workflowPreview";

function makeWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "wf-1",
    name: "Page",
    description: null,
    nodes: [],
    edges: [],
    auth_type: "none",
    sse_enabled: false,
    ...overrides,
  } as Workflow;
}

describe("buildWorkflowCurl", () => {
  it("defaults to POST with a JSON body", () => {
    const command = buildWorkflowCurl(makeWorkflow(), "https://heym.test");
    expect(command).toContain("curl -X POST");
    expect(command).toContain('-H "Content-Type: application/json"');
    expect(command).toContain("-d '");
  });

  it("uses the configured method", () => {
    const command = buildWorkflowCurl(
      makeWorkflow({ http_method: "PUT" }),
      "https://heym.test",
    );
    expect(command).toContain("curl -X PUT");
  });

  it("drops the body and content type for GET", () => {
    const command = buildWorkflowCurl(
      makeWorkflow({ http_method: "GET" }),
      "https://heym.test",
    );
    expect(command).toContain("curl -X GET");
    expect(command).not.toContain("Content-Type");
    expect(command).not.toContain("-d '");
  });

  it("drops the body for DELETE", () => {
    const command = buildWorkflowCurl(
      makeWorkflow({ http_method: "DELETE" }),
      "https://heym.test",
    );
    expect(command).toContain("curl -X DELETE");
    expect(command).not.toContain("-d '");
  });
});
```

Adjust `makeWorkflow`'s literal fields to satisfy the real `Workflow` interface — read it
first and fill in whatever is required.

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd frontend && bun run test src/lib/workflowPreview.test.ts
```

Expected: the PUT/GET/DELETE cases FAIL — the builder hardcodes `curl -X POST`.

- [ ] **Step 4: Make the preview builder method-aware**

In `frontend/src/lib/workflowPreview.ts`, replace the whole body of `buildWorkflowCurl`:

```typescript
export function buildWorkflowCurl(workflow: Workflow, origin?: string): string {
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  const path = workflow.sse_enabled
    ? `/api/workflows/${workflow.id}/execute/stream`
    : `/api/workflows/${workflow.id}/execute`;
  const url = `${base.replace(/\/$/, "")}${path}`;

  const method = (workflow.http_method || "POST").toUpperCase();
  const sendsBody = method !== "GET" && method !== "DELETE";

  const headers = ['-H "X-Trigger-Source: API"'];
  if (sendsBody) {
    headers.unshift('-H "Content-Type: application/json"');
  }
  if (workflow.sse_enabled) {
    headers.push('-H "Accept: text/event-stream"');
  }
  if (workflow.auth_type === "header_auth") {
    headers.push(`-H "${workflow.auth_header_key || "X-API-Key"}: <your-secret-value>"`);
  } else if (workflow.auth_type === "jwt") {
    headers.push('-H "Authorization: Bearer <your-execution-token>"');
  }

  const lines = [
    `curl -X ${method}${workflow.sse_enabled ? " --no-buffer" : ""} \\`,
    ...headers.map((header) => `  ${header} \\`),
  ];
  if (sendsBody) {
    const body = JSON.stringify(buildSampleInputs(workflow));
    lines.push(`  "${url}" \\`, `  -d '${body}'`);
  } else {
    lines.push(`  "${url}"`);
  }
  return lines.join("\n");
}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd frontend && bun run test src/lib/workflowPreview.test.ts
```

Expected: 4 passed.

- [ ] **Step 6: Add the selector to the editor dialog**

In `frontend/src/views/EditorView.vue`, next to line 98 (`const sseEnabled = ref(false);`) add:

```typescript
const httpMethod = ref("POST");
const HTTP_METHODS = ["GET", "POST", "PUT", "DELETE"] as const;
const sendsRequestBody = computed(
  () => httpMethod.value !== "GET" && httpMethod.value !== "DELETE",
);
```

At line 879, next to `sseEnabled.value = workflow.sse_enabled ?? false;`, add:

```typescript
    httpMethod.value = workflow.http_method ?? "POST";
```

At line 867 (the reset branch that sets `sseEnabled.value = false;`), add:

```typescript
    httpMethod.value = "POST";
```

Next to `saveSseEnabled` (line ~955), add:

```typescript
async function saveHttpMethod(): Promise<void> {
  await workflowApi.update(workflowId.value, { http_method: httpMethod.value });
  if (workflowStore.currentWorkflow) {
    workflowStore.currentWorkflow.http_method = httpMethod.value;
  }
}
```

- [ ] **Step 7: Make the editor's cURL method-aware**

Replace the **entire body** of the `curlCommand` computed in `frontend/src/views/EditorView.vue`
(currently lines 1032-1075) with this. Note the payload is only built when the method actually
sends one — computing it unconditionally would stringify a value the early return no longer
guards on GET.

```typescript
const curlCommand = computed(() => {
  if (curlBodyError.value && sendsRequestBody.value) {
    return "Fix JSON body to generate the cURL command.";
  }

  const basePath = sseEnabled.value
    ? `/api/workflows/${workflowId.value}/execute/stream`
    : `/api/workflows/${workflowId.value}/execute`;
  const url = joinOriginAndPath(window.location.origin, basePath);

  const headerLines: string[] = ['  -H "X-Trigger-Source: API" \\'];
  if (sendsRequestBody.value) {
    headerLines.unshift('  -H "Content-Type: application/json" \\');
  }
  if (!simpleResponse.value) {
    headerLines.push('  -H "X-Simple-Response: false" \\');
  }
  if (sseEnabled.value) {
    headerLines.push('  -H "Accept: text/event-stream" \\');
  }
  if (authType.value === "jwt") {
    const activeToken = executionTokens.value.find((t) => t.id === selectedTokenId.value);
    const bearer = activeToken ? activeToken.token : "<your-execution-token>";
    headerLines.push(`  -H "Authorization: Bearer ${bearer}" \\`);
  } else if (authType.value === "header_auth") {
    const key = authHeaderKey.value || "X-API-Key";
    const value = authHeaderValue.value || "your-secret-value";
    headerLines.push(`  -H "${key}: ${value}" \\`);
  }

  const commandLines = [
    `curl -X ${httpMethod.value}${sseEnabled.value ? " --no-buffer" : ""} \\`,
    ...headerLines,
  ];

  if (sendsRequestBody.value) {
    const payload = stringifyWebhookJson(curlPayload.value);
    const escapedPayload = payload.replace(/'/g, "'\\''");
    const indentedPayload = escapedPayload
      .split("\n")
      .map((line, index) => (index === 0 ? line : `  ${line}`))
      .join("\n");
    commandLines.push(`  "${url}" \\`, `  -d '${indentedPayload}'`);
  } else {
    commandLines.push(`  "${url}"`);
  }

  return commandLines.join("\n");
});
```


- [ ] **Step 8: Add the selector markup**

In the template, immediately above the Simple Response block (line 2196, the
`<div class="border-t pt-4">` containing the Simple Response label), insert:

```vue
        <div class="border-t pt-4">
          <div class="flex items-center justify-between gap-3 pr-4">
            <div>
              <Label class="text-sm font-medium">Request Method</Label>
              <p class="mt-0.5 text-xs text-muted-foreground">
                The verb this workflow accepts. Other methods are rejected with 405.
              </p>
            </div>
            <select
              id="http-method"
              v-model="httpMethod"
              class="h-9 rounded border border-input bg-background px-2 text-sm"
              @change="saveHttpMethod"
            >
              <option
                v-for="method in HTTP_METHODS"
                :key="method"
                :value="method"
              >
                {{ method }}
              </option>
            </select>
          </div>
        </div>
```

Add `v-if="sendsRequestBody"` to the request-body block (the `<div class="space-y-2">`
wrapping the `Raw JSON Body` / `Defined Request Body` label and the `curlInput` textarea at
line ~2214), so GET and DELETE hide it.

- [ ] **Step 9: Verify**

```bash
cd frontend && bun run typecheck && bun run lint && bun run test
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/views/EditorView.vue \
        frontend/src/lib/workflowPreview.ts frontend/src/lib/workflowPreview.test.ts
git commit -m "Add a request-method selector driving both cURL snippets"
```

---

## Task 15: heymrun documentation

**Files:**
- Create: `frontend/src/docs/content/nodes/html-output-mapper-node.md`
- Modify: `frontend/src/docs/manifest.ts:88`
- Modify: `frontend/src/docs/content/reference/node-types.md:93`
- Modify: `frontend/src/docs/content/reference/features.md:375`, `:423`
- Modify: `frontend/src/docs/content/reference/webhooks.md`
- Modify: `frontend/src/docs/content/tabs/workflows-tab.md`

Invoke the `heym-documentation` skill before writing these — AGENTS.md requires it for
documentation changes.

- [ ] **Step 1: Write the node page**

Create `frontend/src/docs/content/nodes/html-output-mapper-node.md`:

```markdown
# HTML output mapper

The **HTML output mapper** node renders a single HTML template into a page. Use it when the caller is a **browser** rather than an API client — the workflow answers with `text/html` instead of JSON.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 0 (sink) |
| Runtime output | `{ "html": "…", "statusCode": 200, "contentType": "text/html; charset=utf-8" }` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `html` | string | The page template. `$nodeLabel.field` expressions are interpolated in place. |
| `statusCode` | number | HTTP status for the response (default `200`) |
| `contentType` | string | Response content type (default `text/html; charset=utf-8`) |

## Webhook and run behavior

When this node is the **only** terminal output of the workflow, the execute endpoint responds with the rendered page, the configured status code, and the configured content type — no JSON envelope, no label wrapper.

Two things turn that off:

- **A second terminal node.** With another active terminal in the graph, Heym falls back to the normal per-label JSON map and the page arrives as a string field.
- **`X-Simple-Response: false`.** That header asks for the full envelope with `status`, `node_results`, and timings, which is what the editor's canvas uses. Send it when you are debugging a page workflow.

## Serving a page to a browser

Set the workflow's **request method** to `GET` in the cURL dialog so a plain browser navigation reaches it. A `GET` request carries no body, so inputs come from the query string:

```
curl -X GET "https://your-host/api/workflows/<workflow-id>/execute?name=Ada"
```

Read those values with `$input.query.name`. See [Webhooks](../reference/webhooks.md) for the full method contract.

A workflow with no trigger node whose only terminal is this node shows a **WEB** chip in the [Workflows tab](../tabs/workflows-tab.md).

## Agent tool usage

Not supported. This node is a terminal sink, so it cannot be attached to an [Agent Node](./agent-node.md) tools handle. The same applies to [JSON output mapper](./json-output-mapper-node.md).

## Loop restriction

Same rule as [Output](./output-node.md): do not place this node inside a loop iteration branch—only after the loop `done` branch. See [Loop](./loop-node.md).

## Example

```json
{
  "type": "htmlOutputMapper",
  "data": {
    "label": "reportPage",
    "html": "<!doctype html><html><body><h1>$llm.text</h1><p>Generated by Heym</p></body></html>",
    "statusCode": 200,
    "contentType": "text/html; charset=utf-8"
  }
}
```

## Related

- [JSON output mapper](./json-output-mapper-node.md) – Same idea for API clients expecting JSON
- [Output](./output-node.md) – Message or schema-based response with `result` wrapping
- [Webhooks](../reference/webhooks.md) – Execute endpoint, request methods, and responses
- [Node Types](../reference/node-types.md) – All node types
```

- [ ] **Step 1b: Correct the JSON output mapper page**

`frontend/src/docs/content/nodes/json-output-mapper-node.md` currently carries an
**Agent tool usage** section describing bot-icon agent-provided mappings. Task 8 makes that
false. Find the section:

```markdown
## Agent tool usage

When JSON output mapper is connected to an [Agent Node](./agent-node.md) as a canvas node tool, mapping values can be marked as **agent-provided** with the bot icon. Marked values become required tool parameters supplied by the agent at runtime. Unmarked values remain fixed.

The bot icon appears only while the mapper is connected to an agent's tools handle.
```

Replace it with:

```markdown
## Agent tool usage

Not supported. This node is a terminal sink, so it cannot be attached to an [Agent Node](./agent-node.md) tools handle. Use a [Set](./set-node.md) node when an agent needs to shape values mid-conversation.
```

Then check whether any other doc repeats the claim:

```bash
cd frontend && grep -rn "jsonOutputMapper\|JSON output mapper" src/docs/content/ | grep -i "tool"
```

Correct every hit the same way.

- [ ] **Step 2: Register it in the manifest**

In `frontend/src/docs/manifest.ts`, find line 88:

```typescript
      { slug: "json-output-mapper-node", title: "JSON output mapper" },
```

Insert directly after it:

```typescript
      { slug: "html-output-mapper-node", title: "HTML output mapper" },
```

- [ ] **Step 3: Add the node-types table row**

In `frontend/src/docs/content/reference/node-types.md`, find line 93:

```markdown
| [JSON output mapper](../nodes/json-output-mapper-node.md) | Map fields to a JSON object; sole terminal = top-level webhook/run body | 1 | 0 |
```

Insert directly after it:

```markdown
| [HTML output mapper](../nodes/html-output-mapper-node.md) | Render an HTML page; sole terminal = webhook responds with text/html | 1 | 0 |
```

- [ ] **Step 4: Add the features.md section**

In `frontend/src/docs/content/reference/features.md`, after the JSON output mapper section
(line 375-377 plus whatever follows it before the next `####`), add:

```markdown
#### [HTML output mapper](../nodes/html-output-mapper-node.md)

The HTML output mapper node renders a single HTML template, interpolating `$nodeLabel.field`
expressions into the page. When it is the workflow's only terminal node, the execute webhook
responds with `text/html` and the node's configured status code instead of a JSON body, so a
workflow can serve a page directly to a browser. Send `X-Simple-Response: false` to get the
usual JSON envelope back for debugging.
```

In the same file, line 423, extend the utilities list. Find:

```markdown
[JSON output mapper](../nodes/json-output-mapper-node.md), [Console Log](../nodes/console-log-node.md)
```

Replace with:

```markdown
[JSON output mapper](../nodes/json-output-mapper-node.md), [HTML output mapper](../nodes/html-output-mapper-node.md), [Console Log](../nodes/console-log-node.md)
```

- [ ] **Step 5: Document the request method in webhooks.md**

Add this section to `frontend/src/docs/content/reference/webhooks.md`, placed after whatever
section introduces the execute endpoint:

```markdown
## Request method

Each workflow accepts one HTTP verb, chosen in the editor's cURL dialog: `GET`, `POST`, `PUT`, or `DELETE`. **`POST` is the default**, and every workflow created before this setting existed keeps it, so nothing that works today changes.

Calling a workflow with a different verb returns `405 Method Not Allowed` with an `Allow` header naming the configured one:

```
$ curl -X POST "https://your-host/api/workflows/<workflow-id>/execute"
HTTP/1.1 405 Method Not Allowed
Allow: GET
```

One exception: requests carrying `?test_run=true` skip the check. That is what the editor's **Run** button and the debug panel send, so a workflow set to `GET` stays testable from inside the product.

### Bodyless methods

`GET` and `DELETE` carry no request body. Inputs come from the query string instead, and are read with `$input.query.<name>`:

```
curl -X GET "https://your-host/api/workflows/<workflow-id>/execute?name=Ada"
```

The cURL dialog hides the request-body editor and drops the `Content-Type` header for these two methods.

Pair `GET` with an [HTML output mapper](../nodes/html-output-mapper-node.md) to serve a page a browser can open directly.
```

- [ ] **Step 6: Document the WEB chip**

In `frontend/src/docs/content/tabs/workflows-tab.md`, find the list of status chips (it
already documents Running, Scheduled, Listening, Paused, Manual, API, SubWorker, and Portal)
and add an entry in the same format the surrounding entries use:

```markdown
- **WEB** – The workflow has no trigger node and its only terminal is an [HTML output mapper](../nodes/html-output-mapper-node.md), so calling it returns a rendered web page instead of JSON. This chip replaces **Manual**, and takes precedence over **API** even after the workflow has been called over HTTP.
```

Match the surrounding bullets' punctuation and dash style rather than copying this one
verbatim if they differ.

- [ ] **Step 7: Verify the docs build**

```bash
cd frontend && bun run typecheck && bun run build
```

Expected: PASS. A manifest slug with no matching file breaks the docs route.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/docs/
git commit -m "Document the HTML output mapper node and request methods"
```

---

## Task 16: The DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py:34-51`, `:1236`

- [ ] **Step 1: Add section 8c**

In `backend/app/services/workflow_dsl_prompt.py`, immediately after the `### 8b.` block's
final `**Rules**` bullet (line 1237) and before `### 10. wait (Delay)`, insert:

```
### 8c. htmlOutputMapper (HTML response body)
- **Purpose**: Render an HTML page from a single template string. When this node is the **only** terminal output of the workflow, Heym responds to the webhook/run with `text/html` and the configured status code instead of a JSON body.
- **Inputs**: 1 | **Outputs**: 0 (sink; do not connect downstream)
- **Data fields**:
  - `label`: Node identifier (camelCase)
  - `html`: The page template. `$nodeLabel.field` expressions are interpolated in place.
  - `statusCode`: HTTP status for the response (default `200`)
  - `contentType`: Response content type (default `text/html; charset=utf-8`)

**When to use**: Serving a page straight to a browser - a status dashboard, a generated report, a confirmation screen. Use `jsonOutputMapper` instead when the caller is an API client.

**Example**:
```json
{
  "id": "node_html_out",
  "type": "htmlOutputMapper",
  "position": { "x": 600, "y": 100 },
  "data": {
    "label": "reportPage",
    "html": "<!doctype html><html><body><h1>$llmNode.text</h1></body></html>",
    "statusCode": 200,
    "contentType": "text/html; charset=utf-8"
  }
}
```

**Rules**:
- Unwrapping applies **only when the sole terminal is one `htmlOutputMapper`**. With a second terminal the runtime falls back to the normal per-label JSON map.
- Same loop restriction as `output`: **never** place `htmlOutputMapper` inside a loop iteration branch (only after `done`).
- **Never** connect `htmlOutputMapper` to an agent's `tool-input` handle. It is a terminal sink, not a callable tool. The same applies to `jsonOutputMapper`.
```

- [ ] **Step 2: Extend the loop hard rule**

At line 34, find:

```
NEVER place an `output` or `jsonOutputMapper` node anywhere in the loop's iteration path (connected via `sourceHandle: "loop"`). This is a HARD RULE - the workflow validator will REJECT it!
```

Replace with:

```
NEVER place an `output`, `jsonOutputMapper`, or `htmlOutputMapper` node anywhere in the loop's iteration path (connected via `sourceHandle: "loop"`). This is a HARD RULE - the workflow validator will REJECT it!
```

At line 51, find:

```
**INSTEAD**: Use `set` or `variable` nodes for intermediate processing inside loops. `output` and `jsonOutputMapper` belong ONLY on the `done` branch!
```

Replace with:

```
**INSTEAD**: Use `set` or `variable` nodes for intermediate processing inside loops. `output`, `jsonOutputMapper`, and `htmlOutputMapper` belong ONLY on the `done` branch!
```

- [ ] **Step 3: Verify**

```bash
cd backend && uv run ruff check app/services/workflow_dsl_prompt.py && \
  HEYM_OTEL_ENABLED=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes \
  uv run pytest tests/ -k "dsl or prompt" -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "Add htmlOutputMapper to the workflow DSL prompt"
```

---

## Task 17: The release tour entry

**Files:**
- Create: `frontend/src/features/release-tour/components/visuals/HtmlOutputMapperTourVisual.vue`
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts:26`, `:114`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`
- Modify: `frontend/e2e/support.ts`
- Test: `frontend/src/features/release-tour/releaseTourMapper.test.ts` (existing registry test)

- [ ] **Step 1: Add the section to the registry**

In `frontend/src/features/release-tour/releaseRegistry.ts`, find line 26:

```typescript
      sectionOrder: ["workflow-listing", "code-node", "folder-icons", "playwright-ai-steps"],
```

Replace with:

```typescript
      sectionOrder: [
        "workflow-listing",
        "code-node",
        "folder-icons",
        "playwright-ai-steps",
        "html-output-mapper",
      ],
```

Update `introTitle` on line 20 from `"Four new things in this release"` to
`"Five new things in this release"`, and extend `headline` (line 18) to mention pages:

```typescript
    headline:
      "A rebuilt workflow list, Python on the canvas, branded folders, readable Playwright runs, and workflows that serve web pages",
```

After the `playwright-ai-steps` section object (its closing `},` at line 114) and before the
closing `],` of `sections`, insert:

```typescript
      {
        id: "html-output-mapper",
        title: "Workflows that answer with a web page",
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **HTML output mapper** node renders a page from a template, and when it is a workflow's only terminal node the execute webhook responds with `text/html` instead of JSON. The cURL dialog gained a **request method** selector, so a workflow can answer a plain browser `GET`, and the workflow list marks these with a **WEB** chip.",
          },
        ],
        tour: {
          description:
            "Drop an HTML output mapper at the end of a workflow, set the request method to GET, and the workflow's URL opens in a browser as a real page.",
          useCases: [
            "Serve a generated status page without standing up a web server",
            "Return a confirmation screen a person can actually read",
            "Publish a report an Agent writes, straight to a URL",
          ],
          tourVisual: "html-output-mapper",
          docTarget: {
            categoryId: "nodes",
            slug: "html-output-mapper-node",
            title: "HTML output mapper",
          },
        },
      },
```

- [ ] **Step 2: Build the visual**

Create `frontend/src/features/release-tour/components/visuals/HtmlOutputMapperTourVisual.vue`.
It is **mock UI**: Tailwind semantic tokens only, no production API calls, no host-page state.
The four existing visuals in that directory are the reference — `CodeNodeTourVisual.vue` is the
closest in shape.

```vue
<script setup lang="ts">
import { computed } from "vue";
import { FileCode2, Globe } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

const step = useCycleStep(4, 1300);

const method = computed(() => (step.value >= 1 ? "GET" : "POST"));
const showsPage = computed(() => step.value >= 2);
const showsChip = computed(() => step.value >= 3);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 p-3">
    <div class="flex items-center gap-2">
      <div class="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1">
        <FileCode2 class="h-3.5 w-3.5 text-primary" />
        <span class="text-[11px] font-semibold text-foreground">HTML output mapper</span>
      </div>
      <span
        class="rounded border px-1.5 py-0.5 text-[10px] font-semibold transition-colors duration-500"
        :class="method === 'GET'
          ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500'
          : 'border-border bg-muted text-muted-foreground'"
      >{{ method }}</span>
    </div>

    <div class="rounded-lg border border-border bg-surface-sunken px-2 py-1.5">
      <span class="font-mono text-[10.5px] text-muted-foreground">
        curl -X <span class="text-foreground">{{ method }}</span> ".../execute?name=Ada"
      </span>
    </div>

    <div class="flex flex-1 flex-col overflow-hidden rounded-lg border border-border bg-background">
      <div class="flex items-center gap-1 border-b border-border bg-muted/50 px-2 py-1">
        <span class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
        <span class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
        <span class="ml-1 truncate font-mono text-[9.5px] text-muted-foreground">
          heym.local/api/workflows/…/execute
        </span>
      </div>
      <Transition
        enter-active-class="transition-opacity duration-500"
        enter-from-class="opacity-0"
        leave-active-class="transition-opacity duration-300"
        leave-to-class="opacity-0"
        mode="out-in"
      >
        <div
          v-if="showsPage"
          key="page"
          class="flex flex-1 flex-col items-center justify-center gap-1"
        >
          <span class="text-sm font-semibold text-foreground">Hello Ada</span>
          <span class="text-[10px] text-muted-foreground">Generated by Heym</span>
        </div>
        <div
          v-else
          key="json"
          class="flex flex-1 items-center justify-center"
        >
          <span class="font-mono text-[10.5px] text-muted-foreground">{ "page": { … } }</span>
        </div>
      </Transition>
    </div>

    <div
      class="flex items-center gap-2 rounded-lg border px-2 py-1.5 transition-all duration-500"
      :class="showsChip ? 'border-border bg-muted/40 opacity-100' : 'border-transparent opacity-0'"
    >
      <span class="truncate text-[10.5px] text-foreground">Status page</span>
      <span class="ml-auto inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-[10px] font-medium text-rose-500 ring-1 ring-inset ring-rose-500/20">
        <Globe class="h-2.5 w-2.5" />
        WEB
      </span>
    </div>
  </div>
</template>
```

Verify `surface-sunken` and the other semantic tokens used here exist in this codebase — copy
whatever `CodeNodeTourVisual.vue` uses if any name differs. There is no motion library in this
repo; CSS transitions and `<Transition>` are the whole toolkit.

- [ ] **Step 3: Register the visual**

In `frontend/src/features/release-tour/tourVisuals.ts`, add the import:

```typescript
import HtmlOutputMapperTourVisual from "@/features/release-tour/components/visuals/HtmlOutputMapperTourVisual.vue";
```

and the map entry, keeping the object's alphabetical order:

```typescript
export const TOUR_VISUALS: Record<string, Component> = {
  "code-node": CodeNodeTourVisual,
  "folder-icons": FolderIconsTourVisual,
  "html-output-mapper": HtmlOutputMapperTourVisual,
  "playwright-ai-steps": PlaywrightAiStepsTourVisual,
  "workflow-listing": WorkflowListingTourVisual,
};
```

The key must match the section's `tourVisual` value exactly. An unregistered key silently
falls back to `FallbackTourVisual`, which is why `releaseTourMapper.test.ts` guards it.

- [ ] **Step 4: Realign the E2E seed**

In `frontend/e2e/support.ts`, find the seeded `heym-release-tour-seen` versioned id and update
it so it still matches the newest enabled `releaseId` plus the new `sectionOrder` (the stored
id is derived from the slide ids, so adding a section changes it). Follow the existing
derivation in `releaseTourStorage.ts` rather than guessing the string.

- [ ] **Step 5: Verify the registry test passes**

```bash
cd frontend && bun run test src/features/release-tour/releaseTourMapper.test.ts
```

Expected: PASS. This test guards that every `tourVisual` key is registered — an unregistered
key silently falls back to the neutral visual, which is why the test exists.

- [ ] **Step 6: Verify the whole frontend**

```bash
cd frontend && bun run typecheck && bun run lint && bun run test
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/release-tour/ frontend/e2e/support.ts
git commit -m "Announce the HTML output mapper in the release tour"
```

---

## Task 18: heymrun gate

- [ ] **Step 1: Run the repo check**

```bash
\
  SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
```

Expected: frontend lint + typecheck pass, backend ruff passes, backend tests pass.

- [ ] **Step 2: Run the E2E suite**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./run_e2e.sh
```

The full E2E suite is never green locally on this repo. Compare failures against a run on
`c7af349a`; re-run any failing spec in isolation before treating it as a regression. In
particular `getByLabel('Name')` is a known flake — a "Renamed" workflow's pin button collides
with it.

- [ ] **Step 3: Commit any stragglers**

```bash
git add -A && git commit -m "Apply check.sh formatting" || echo "clean"
```

---

## Task 19: heymweb node registration

**Repo:** `/Users/mbakgun/Projects/heym/heymweb`

The node count moves 60 → 61. It is hardcoded in seven places, not two.

- [ ] **Step 1: Add the catalog entry**

In `src/lib/marketingNodeCatalog.ts`, add `{ id: 'htmlOutputMapper', name: 'HTML output mapper' }`
next to the `jsonOutputMapper` entry. This is the count source of truth —
`MARKETING_NODE_COUNT` feeds `DOCUMENTATION_PAGE_COUNT` in `src/lib/documentationStats.ts`.

- [ ] **Step 2: Add the doc link**

In `src/lib/node-doc-links.ts`, add:

```typescript
  htmlOutputMapper: 'nodes/html-output-mapper-node.md',
```

- [ ] **Step 3: Add the marketing card**

In `src/components/sections/NodesSection.tsx`, add a card with `id: 'htmlOutputMapper'`, the
`FileCode2` lucide icon (mirroring heymrun's choice), the name, a one-line description, and
the same `categories` the `jsonOutputMapper` card uses.

- [ ] **Step 4: Add the preview token**

In `src/components/templates/nodePreviewTokens.ts`, add
`htmlOutputMapper: '--node-output'`, reusing the token `jsonOutputMapper` already uses.
Confirm that CSS variable exists in `src/app/globals.css`.

- [ ] **Step 5: Add the canvas icon**

In `src/components/templates/TemplateCanvasNode.tsx`, map `htmlOutputMapper` to `FileCode2`.

- [ ] **Step 6: Add the documentation link**

In `src/components/sections/DocumentationSection.tsx`, add the curated entry for the new node
doc, following the shape of the neighbouring node entries.

- [ ] **Step 7: Bump the seven hardcoded counts**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit
```

This fails first — `tests/seo/invariants.test.ts` uses `expect(MARKETING_NODE_COUNT).toBe(60)`,
and Bun's `toBe` narrows to a literal overload, so a stale number is a **type error**, not
just a test failure. Update all seven:

1. `tests/seo/invariants.test.ts` — the `test('matches all 60 heymrun node definitions...')` title
2. `tests/seo/invariants.test.ts` — `expect(MARKETING_NODE_COUNT).toBe(60)`
3. `README.md` — "Showcase of 60 node types"
4. `src/content/blog/what-is-ai-workflow-automation.mdx` — "supports 60 node types"
5. `public/readme-assets/hero.svg` — "60 NODE TYPES · MCP"
6. `public/readme-assets/workflow-canvas.svg` — "Vue Flow · 60 node types"
7. `public/readme-assets/key-capabilities.svg` — "60 node types"

The `countFiles(docsRoot)` assertion self-corrects, since `DOCUMENTATION_PAGE_COUNT` is derived.

- [ ] **Step 8: Verify**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && \
  bun test tests/seo/invariants.test.ts && bun run build
```

Expected: all PASS. heymweb has no lint or unit-test suite beyond this — `tsc` plus `build`
is the gate.

- [ ] **Step 9: Commit (local only)**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && git add -A && \
  git commit -m "Register the HTML output mapper node"
```

---

## Task 20: heymweb sync and template

**Repo:** `/Users/mbakgun/Projects/heym/heymweb`

- [ ] **Step 1: Sync docs and the DSL prompt from heymrun**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bun run sync-docs && bun run sync-dsl-prompt
```

Both read from `../heymrun`, so Tasks 15 and 16 must be committed first.

- [ ] **Step 2: Add the template**

Add a `StaticTemplate` to the `TEMPLATES` array in `src/lib/templates.ts`. The interface is
declared at the top of that file (`slug`, `name`, `description`, `longDescription`, `tags`,
`category`, `secondaryCategories?`, `nodes`, `edges`, `featured`). Insert it following the
formatting of `workflow-change-audit-log`, the array's first entry.

```typescript
  {
    slug: 'html-status-page',
    name: 'HTML Status Page',
    description: 'Check an upstream service and answer a browser GET with a rendered status page instead of JSON.',
    longDescription: `## HTML Status Page

This template turns a workflow into a page a person can open. An **HTTP** node checks an upstream service, and an **HTML output mapper** renders the result as a real web page. Because the mapper is the workflow's only terminal node, the execute endpoint answers with \`text/html\` rather than a JSON body.

### What this workflow does

1. **ServiceCheck** calls the upstream health endpoint
2. **StatusPage** renders the response into an HTML document and returns it with a 200

### Use cases

- A public status page for a service that has no dashboard of its own
- A generated report you can bookmark instead of curl
- A confirmation screen at the end of a form submission flow

### Setup

Point **ServiceCheck** at the URL you want to watch. In the workflow's cURL dialog, set the **request method** to \`GET\` so a plain browser navigation reaches it, then open the workflow's execute URL in a tab.

### Notes

Values from the query string are available as \`$input.query.<name>\`, since a GET request carries no body. Send \`X-Simple-Response: false\` to get the usual JSON envelope back while debugging. Adding a second terminal node turns the HTML response off - the run falls back to the normal per-label JSON map.`,
    tags: ['HTML', 'Status Page', 'Webhook', 'Monitoring', 'Web'],
    category: 'DevOps',
    secondaryCategories: ['Automation'],
    featured: false,
    nodes: [
      {
        id: 'status_check',
        type: 'http',
        position: { x: 100, y: 200 },
        data: {
          label: 'ServiceCheck',
          url: 'https://example.com/health',
          method: 'GET'
        }
      },
      {
        id: 'status_page',
        type: 'htmlOutputMapper',
        position: { x: 420, y: 200 },
        data: {
          label: 'StatusPage',
          statusCode: 200,
          contentType: 'text/html; charset=utf-8',
          html: '<!doctype html><html><head><title>Service status</title></head><body><h1>Service status</h1><p>Upstream replied: $ServiceCheck.status</p><pre>$ServiceCheck.body</pre></body></html>'
        }
      }
    ],
    edges: [
      { id: 'status_e1', source: 'status_check', target: 'status_page' }
    ]
  },
```

Two constraints that have broken this file before:

- `WorkflowTemplateCard` draws its canvas only if the `json` attribute parses **in the
  browser**. JSX attributes are literal, so `\\"` breaks it - use single backslashes and verify
  the exact bytes rather than validating with Python's `unicode_escape`, which is a fake check
  that has already shipped a dead card once.
- Confirm `'DevOps'` is a valid `TemplateCategory` in `src/lib/templateCategories.ts` before
  using it; substitute the closest valid one if not.

- [ ] **Step 3: Verify**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && \
  bun test tests/seo/invariants.test.ts && bun run build
```

Expected: all PASS.

- [ ] **Step 4: Load the template page and confirm the canvas renders**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bun run dev
```

Open the new template's page and confirm the canvas preview draws all three nodes. A blank
canvas means the `json` attribute failed to parse — fix the escaping before committing.
Note: `next-server` survives `pkill` and will serve a stale build; kill it explicitly.

- [ ] **Step 5: Commit (local only)**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && git add -A && \
  git commit -m "Sync heymrun docs and add the HTML status page template"
```

---

## Task 21: Final verification

- [ ] **Step 1: Run both repos' gates one more time**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && \
  SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build
```

Expected: both clean.

- [ ] **Step 2: Manual smoke test**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./run.sh
```

Then, in the browser at `http://localhost:4017`:

1. Create a workflow: `textInput` → `htmlOutputMapper` with
   `<h1>Hello $userInput.name</h1>` in the HTML body.
2. Confirm the node shows no output handle and cannot be dragged onto an agent's tool handle.
3. Open the cURL dialog, set the method to **GET**, confirm the command drops `-d` and the
   body textarea disappears.
4. Save, return to the Workflows tab, and confirm the row shows a **WEB** chip and its preview
   panel cURL says `-X GET`.
5. Open `http://localhost:10105/api/workflows/<id>/execute?name=Ada` in a browser tab.
   Expected: a rendered `<h1>Hello Ada</h1>`, not JSON.
6. `curl -X POST` the same URL. Expected: `405` with `Allow: GET`.
7. Press Run in the editor. Expected: it still works, despite the method being GET.
8. Confirm the release tour's fifth slide appears and its visual animates.

- [ ] **Step 3: Report**

Summarize what was built, what passed, and anything left open. Do **not** push — this repo
requires explicit approval for every push.
