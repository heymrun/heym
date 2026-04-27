# Unified Expression Evaluator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge ExpressionInput's two evaluation modes (expression/template) into one unified backend-evaluated flow, adding a Run button, enlarged dialog, and "Evaluate — fieldName" header.

**Architecture:** A new `ExpressionEvaluatorService` is extracted from `WorkflowExecutor`, exposed via `POST /api/expressions/evaluate`, and called from the frontend Run button. All frontend preview logic is removed. Context is built from DB-persisted `pinnedData` + request-body `node_results` (canvas last-run outputs).

**Tech Stack:** Python 3.11 / FastAPI / Pydantic / simpleeval / Vue 3 + TypeScript / axios

---

## File Map

### Created
- `backend/app/services/expression_evaluator.py` — `ExpressionEvaluatorService`, context builder, type classifier
- `backend/app/api/expressions.py` — FastAPI router: `POST /api/expressions/evaluate`
- `backend/tests/test_expression_evaluator_service.py` — unit tests for service
- `backend/tests/test_expression_evaluator_api.py` — unit tests for API route

### Modified
- `backend/app/services/workflow_executor.py` — import `_is_single_dollar_expression` from service (no behavioural change)
- `backend/app/main.py` — register expressions router
- `backend/tests/test_output_message_template_resolve.py` — extend with service wrapper cases
- `frontend/src/services/api.ts` — add `expressionApi.evaluate()`
- `frontend/src/types/workflow.ts` — add `ExpressionEvaluateRequest` / `ExpressionEvaluateResponse` types
- `frontend/src/components/ui/ExpressionInput.vue` — remove preview logic, add Run button, new header/size
- `frontend/src/components/Panels/PropertiesPanel.vue` — remove all `evaluation-mode` attributes
- `frontend/src/components/ui/JsonInputPanel.vue` — remove `evaluationMode` prop forwarding
- `backend/app/services/workflow_dsl_prompt.py` — update prompt (remove mode distinction)
- `frontend/src/docs/content/reference/expression-evaluation-dialog.md` — rewrite
- `frontend/src/docs/content/reference/expression-dsl.md` — add type-preservation note

---

## Task 1 — Write failing tests for ExpressionEvaluatorService

**Files:**
- Create: `backend/tests/test_expression_evaluator_service.py`

- [ ] **Step 1.1: Create the test file**

```python
# backend/tests/test_expression_evaluator_service.py
import unittest
from unittest.mock import MagicMock, patch


class TestIsSingleDollarExpression(unittest.TestCase):
    """Tests for the standalone _is_single_dollar_expression helper."""

    def _make_executor(self):
        # We'll import from the service module once it exists;
        # for now import from the service path we're about to create.
        from app.services.expression_evaluator import is_single_dollar_expression
        return is_single_dollar_expression

    def test_plain_dollar_ref(self):
        f = self._make_executor()
        self.assertTrue(f("$input.text"))

    def test_dollar_ref_with_method(self):
        f = self._make_executor()
        self.assertTrue(f("$llm.text.upper()"))

    def test_dollar_ref_with_bracket(self):
        f = self._make_executor()
        self.assertTrue(f("$node.headers['x-api-key']"))

    def test_template_with_prefix(self):
        f = self._make_executor()
        self.assertFalse(f("Hello $input.name"))

    def test_template_with_suffix(self):
        f = self._make_executor()
        self.assertFalse(f("$input.name suffix"))

    def test_template_two_refs(self):
        f = self._make_executor()
        self.assertFalse(f("$a.x and $b.y"))

    def test_literal_no_dollar(self):
        f = self._make_executor()
        self.assertFalse(f("just text"))

    def test_empty_string(self):
        f = self._make_executor()
        self.assertFalse(f(""))

    def test_currency_style_value(self):
        # "$100" is a currency literal, not an expression
        f = self._make_executor()
        self.assertFalse(f("$100"))

    def test_arithmetic_is_single(self):
        # "$input.count + 1" — starts with $, whole thing is one expr
        f = self._make_executor()
        self.assertTrue(f("$input.count + 1"))

    def test_ternary_is_single(self):
        f = self._make_executor()
        self.assertTrue(f("$x > 0 ? 'pos' : 'neg'"))


class TestClassifyType(unittest.TestCase):
    def _fn(self):
        from app.services.expression_evaluator import classify_type
        return classify_type

    def test_string(self):
        self.assertEqual(self._fn()("hello"), "string")

    def test_integer(self):
        self.assertEqual(self._fn()(42), "number")

    def test_float(self):
        self.assertEqual(self._fn()(3.14), "number")

    def test_boolean_true(self):
        self.assertEqual(self._fn()(True), "boolean")

    def test_boolean_false(self):
        self.assertEqual(self._fn()(False), "boolean")

    def test_list(self):
        self.assertEqual(self._fn()([1, 2, 3]), "array")

    def test_dict(self):
        self.assertEqual(self._fn()({"a": 1}), "object")

    def test_none(self):
        self.assertEqual(self._fn()(None), "null")


class TestBuildEvalContext(unittest.TestCase):
    def _service(self):
        from app.services.expression_evaluator import build_eval_context
        return build_eval_context

    def _node(self, label: str, pinned=None):
        return {"data": {"label": label, "pinnedData": pinned}}

    def test_pinned_data_injected(self):
        nodes = [self._node("myLlm", pinned={"text": "hello"})]
        result = self._service()(nodes, [])
        self.assertEqual(result["myLlm"]["text"], "hello")

    def test_canvas_output_fills_when_no_pinned(self):
        nodes = [self._node("myLlm")]
        canvas = [{"label": "myLlm", "output": {"text": "world"}}]
        result = self._service()(nodes, canvas)
        self.assertEqual(result["myLlm"]["text"], "world")

    def test_pinned_wins_over_canvas(self):
        nodes = [self._node("myLlm", pinned={"text": "pinned"})]
        canvas = [{"label": "myLlm", "output": {"text": "canvas"}}]
        result = self._service()(nodes, canvas)
        self.assertEqual(result["myLlm"]["text"], "pinned")

    def test_missing_node_not_in_context(self):
        nodes = [self._node("myLlm")]  # no pinned, no canvas
        result = self._service()(nodes, [])
        # label not injected when no data available
        self.assertNotIn("myLlm", result)

    def test_multiple_nodes_all_injected(self):
        nodes = [
            self._node("nodeA", pinned={"x": 1}),
            self._node("nodeB", pinned={"y": 2}),
        ]
        result = self._service()(nodes, [])
        self.assertIn("nodeA", result)
        self.assertIn("nodeB", result)


class TestExpressionEvaluatorServiceEvaluate(unittest.TestCase):
    """Tests for ExpressionEvaluatorService.evaluate()."""

    def _service(self):
        from app.services.expression_evaluator import ExpressionEvaluatorService
        return ExpressionEvaluatorService()

    def _ctx(self, **kwargs):
        """Build a simple context dict with given label→dict mappings."""
        return kwargs

    def test_single_expr_string_result(self):
        svc = self._service()
        ctx = self._ctx(user={"name": "Ali"})
        resp = svc.evaluate("$user.name", ctx)
        self.assertEqual(resp.result, "Ali")
        self.assertEqual(resp.result_type, "string")
        self.assertIsNone(resp.error)

    def test_single_expr_array_preserved(self):
        svc = self._service()
        ctx = self._ctx(data={"items": [1, 2, 3]})
        resp = svc.evaluate("$data.items", ctx)
        self.assertIsInstance(resp.result, list)
        self.assertEqual(resp.result, [1, 2, 3])
        self.assertEqual(resp.result_type, "array")
        self.assertTrue(resp.preserved_type)

    def test_single_expr_object_preserved(self):
        svc = self._service()
        ctx = self._ctx(data={"meta": {"key": "val"}})
        resp = svc.evaluate("$data.meta", ctx)
        self.assertIsInstance(resp.result, dict)
        self.assertEqual(resp.result_type, "object")
        self.assertTrue(resp.preserved_type)

    def test_single_expr_boolean_preserved(self):
        svc = self._service()
        ctx = self._ctx(data={"active": True})
        resp = svc.evaluate("$data.active", ctx)
        self.assertIs(resp.result, True)
        self.assertEqual(resp.result_type, "boolean")

    def test_single_expr_number_preserved(self):
        svc = self._service()
        ctx = self._ctx(data={"count": 42})
        resp = svc.evaluate("$data.count", ctx)
        self.assertEqual(resp.result, 42)
        self.assertEqual(resp.result_type, "number")

    def test_template_string_concatenation(self):
        svc = self._service()
        ctx = self._ctx(user={"name": "John"})
        resp = svc.evaluate("Hello $user.name", ctx)
        self.assertEqual(resp.result, "Hello John")
        self.assertEqual(resp.result_type, "string")
        self.assertFalse(resp.preserved_type)

    def test_template_two_refs(self):
        svc = self._service()
        ctx = self._ctx(a={"x": "foo"}, b={"y": "bar"})
        resp = svc.evaluate("$a.x and $b.y", ctx)
        self.assertEqual(resp.result, "foo and bar")

    def test_arithmetic_expression(self):
        svc = self._service()
        ctx = self._ctx(data={"count": 5})
        resp = svc.evaluate("$data.count + 1", ctx)
        self.assertEqual(resp.result, 6)

    def test_ternary_expression(self):
        svc = self._service()
        ctx = self._ctx(data={"x": 10})
        resp = svc.evaluate("$data.x > 0 ? 'pos' : 'neg'", ctx)
        self.assertEqual(resp.result, "pos")

    def test_string_method_upper(self):
        svc = self._service()
        ctx = self._ctx(data={"text": "hello"})
        resp = svc.evaluate("$data.text.upper()", ctx)
        self.assertEqual(resp.result, "HELLO")

    def test_array_method_filter(self):
        svc = self._service()
        ctx = self._ctx(data={"nums": [1, 2, 3, 4, 5]})
        resp = svc.evaluate("$data.nums.filter('item > 3')", ctx)
        self.assertIsInstance(resp.result, list)
        self.assertEqual(resp.result, [4, 5])

    def test_invalid_expression_returns_error_field(self):
        svc = self._service()
        resp = svc.evaluate("$@@invalid@@", {})
        self.assertIsNotNone(resp.error)
        self.assertIsNone(resp.result)

    def test_undefined_label_resolves_to_none(self):
        svc = self._service()
        resp = svc.evaluate("$unknown.field", {})
        # Should not raise; result is None
        self.assertIsNone(resp.result)
        self.assertIsNone(resp.error)

    def test_literal_no_dollar_returned_as_is(self):
        svc = self._service()
        resp = svc.evaluate("just text", {})
        self.assertEqual(resp.result, "just text")
        self.assertEqual(resp.result_type, "string")

    def test_empty_expression_returns_empty_string(self):
        svc = self._service()
        resp = svc.evaluate("", {})
        self.assertEqual(resp.result, "")

    def test_range_function(self):
        svc = self._service()
        resp = svc.evaluate("$range(1, 5)", {})
        self.assertEqual(resp.result, [1, 2, 3, 4])

    def test_array_function(self):
        svc = self._service()
        resp = svc.evaluate('$array(1, 2, 3)', {})
        self.assertEqual(resp.result, [1, 2, 3])

    def test_expression_over_length_limit_raises(self):
        from app.services.expression_evaluator import ExpressionTooLongError
        svc = self._service()
        with self.assertRaises(ExpressionTooLongError):
            svc.evaluate("$" + "x" * 10001, {})

    def test_multiline_template(self):
        svc = self._service()
        ctx = self._ctx(data={"name": "World"})
        resp = svc.evaluate("Hello\n$data.name\nDone", ctx)
        self.assertIn("World", resp.result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.2: Run tests — confirm they ALL fail with ImportError**

```bash
cd backend && uv run pytest tests/test_expression_evaluator_service.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.services.expression_evaluator'`

---

## Task 2 — Implement ExpressionEvaluatorService

**Files:**
- Create: `backend/app/services/expression_evaluator.py`

- [ ] **Step 2.1: Create the service file**

```python
# backend/app/services/expression_evaluator.py
"""
Standalone expression evaluation service.

Extracted from WorkflowExecutor to provide a dedicated, testable unit
for the /api/expressions/evaluate endpoint. WorkflowExecutor imports
helpers from here; no behavioural change to existing execution paths.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

EXPRESSION_MAX_LENGTH = 10_000


class ExpressionTooLongError(ValueError):
    """Raised when the expression string exceeds the maximum allowed length."""


@dataclass
class ExpressionEvaluateResponse:
    result: Any
    result_type: str
    preserved_type: bool
    error: str | None


def is_single_dollar_expression(template: str) -> bool:
    """
    True when the whole trimmed string is a single $ expression (not a text template).

    Mirrors WorkflowExecutor._is_single_dollar_expression exactly so the
    frontend preview and the executor agree on type-preservation decisions.
    """
    # Import lazily to avoid circular imports with workflow_executor
    from app.services.workflow_executor import WorkflowExecutor  # noqa: PLC0415

    # Use a lightweight executor instance — we only call a pure string method.
    # WorkflowExecutor.__init__ only sets attributes; no I/O is performed.
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    return executor._is_single_dollar_expression(template)


def classify_type(value: Any) -> str:
    """Return a JSON-schema-style type name for *value*."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def build_eval_context(
    workflow_nodes: list[dict],
    canvas_results: list[dict],
) -> dict[str, Any]:
    """
    Build a label→output mapping for use as expression context.

    Priority (highest first):
      1. node.data.pinnedData  — explicitly pinned by the user; persisted in the DB.
      2. canvas_results entry  — last-run output sent by the frontend from its store.

    Nodes with neither source are omitted (expressions referencing them resolve to null).

    Args:
        workflow_nodes: raw node dicts from the stored workflow (include `data.label`,
                        `data.pinnedData`).
        canvas_results: list of {label, output} dicts sent in the API request body.
    """
    canvas_by_label: dict[str, Any] = {
        r["label"]: r["output"] for r in canvas_results if r.get("label")
    }

    context: dict[str, Any] = {}
    for node in workflow_nodes:
        data = node.get("data", {})
        label = data.get("label")
        if not label:
            continue
        pinned = data.get("pinnedData")
        if pinned is not None:
            context[label] = pinned
        elif label in canvas_by_label:
            context[label] = canvas_by_label[label]
        # else: node not in context; expressions referencing it resolve to null

    return context


class ExpressionEvaluatorService:
    """
    Evaluate a single expression or template string against a context dict.

    Context must be a {label: output_dict} mapping — use build_eval_context()
    to construct it from workflow nodes + canvas results.
    """

    def evaluate(
        self,
        expression: str,
        context: dict[str, Any],
    ) -> ExpressionEvaluateResponse:
        """
        Evaluate *expression* against *context*.

        - Single $ expression  → resolve_expression(preserve_type=True)
        - Template (prose+$refs) → evaluate_message_template()
        - No $ present           → return literal string as-is
        """
        if len(expression) > EXPRESSION_MAX_LENGTH:
            raise ExpressionTooLongError(
                f"Expression length {len(expression)} exceeds maximum {EXPRESSION_MAX_LENGTH}"
            )

        if not expression:
            return ExpressionEvaluateResponse(
                result="", result_type="string", preserved_type=False, error=None
            )

        # Import here to avoid circular imports at module load time.
        from app.services.workflow_executor import WorkflowExecutor  # noqa: PLC0415

        executor = WorkflowExecutor.__new__(WorkflowExecutor)
        # Minimal state needed by resolve_expression / evaluate_message_template:
        executor.label_to_output = {}
        executor.vars = {}
        executor.global_variables_context = {}
        executor.credentials_context = {}

        try:
            if is_single_dollar_expression(expression):
                raw = executor.resolve_expression(
                    expression, context, preserve_type=True
                )
                result = executor._unwrap_value(raw)
                return ExpressionEvaluateResponse(
                    result=result,
                    result_type=classify_type(result),
                    preserved_type=True,
                    error=None,
                )
            elif "$" in expression:
                result = executor.evaluate_message_template(expression, context)
                return ExpressionEvaluateResponse(
                    result=result,
                    result_type=classify_type(result),
                    preserved_type=False,
                    error=None,
                )
            else:
                # Literal string — no $ present
                return ExpressionEvaluateResponse(
                    result=expression,
                    result_type="string",
                    preserved_type=False,
                    error=None,
                )
        except Exception as exc:  # noqa: BLE001
            return ExpressionEvaluateResponse(
                result=None,
                result_type="null",
                preserved_type=False,
                error=str(exc),
            )
```

- [ ] **Step 2.2: Run tests — confirm they pass**

```bash
cd backend && uv run pytest tests/test_expression_evaluator_service.py -v
```

Expected: all tests PASS.

> If `WorkflowExecutor.__new__` approach causes issues (e.g. missing `__init__` state), instantiate a real executor with a mock DB session: `WorkflowExecutor(db=MagicMock(), workflow=MagicMock(nodes=[], edges=[]))`. Adjust accordingly.

- [ ] **Step 2.3: Commit**

```bash
cd backend && git add app/services/expression_evaluator.py tests/test_expression_evaluator_service.py
git commit -m "feat: add ExpressionEvaluatorService with unit tests"
```

---

## Task 3 — Write failing tests for the API endpoint

**Files:**
- Create: `backend/tests/test_expression_evaluator_api.py`

- [ ] **Step 3.1: Create the test file**

```python
# backend/tests/test_expression_evaluator_api.py
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient


def _make_app():
    """Import app after patching DB so startup doesn't connect."""
    from app.main import app
    return app


def _auth_headers():
    """Return headers that pass the auth dependency."""
    # Reuse pattern from other API tests in this codebase:
    # patch get_current_user to return a mock user.
    return {"Authorization": "Bearer testtoken"}


WORKFLOW_ID = str(uuid4())
NODE_ID = "node-abc"


class TestExpressionEvaluateEndpoint(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Patch DB session and auth for all tests
        self.mock_user = MagicMock(id=uuid4(), email="test@test.com")
        self.mock_workflow = MagicMock()
        self.mock_workflow.nodes = [
            {"id": NODE_ID, "data": {"label": "myInput", "pinnedData": {"text": "pinned_value"}}}
        ]

    def _client(self, mock_user, mock_workflow):
        from app.main import app
        from app.api.deps import get_current_user
        from app.db.database import get_db

        async def _override_db():
            db = AsyncMock()
            # workflows.get_workflow returns the mock workflow
            db.execute = AsyncMock()
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: mock_user
        return TestClient(app)

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_auth_required(self, _):
        from app.main import app
        client = TestClient(app)
        resp = client.post(f"/api/expressions/evaluate", json={
            "expression": "$x.y",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        })
        self.assertEqual(resp.status_code, 401)

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_valid_request_returns_200(self, mock_get_wf):
        mock_get_wf.return_value = self.mock_workflow
        client = self._client(self.mock_user, self.mock_workflow)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "hello world",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("result", data)
        self.assertIn("result_type", data)
        self.assertIn("preserved_type", data)
        self.assertIn("error", data)

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_pinned_data_used_as_context(self, mock_get_wf):
        mock_get_wf.return_value = self.mock_workflow
        client = self._client(self.mock_user, self.mock_workflow)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$myInput.text",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
            "node_results": [],
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "pinned_value")

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_canvas_node_results_used_when_no_pinned(self, mock_get_wf):
        wf = MagicMock()
        wf.nodes = [{"id": NODE_ID, "data": {"label": "myLlm", "pinnedData": None}}]
        mock_get_wf.return_value = wf
        client = self._client(self.mock_user, wf)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$myLlm.text",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
            "node_results": [{"label": "myLlm", "output": {"text": "canvas_output"}}],
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "canvas_output")

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_pinned_wins_over_canvas(self, mock_get_wf):
        mock_get_wf.return_value = self.mock_workflow  # has pinnedData: {text: "pinned_value"}
        client = self._client(self.mock_user, self.mock_workflow)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$myInput.text",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
            "node_results": [{"label": "myInput", "output": {"text": "canvas_value"}}],
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "pinned_value")

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_workflow_not_found_returns_404(self, mock_get_wf):
        mock_get_wf.return_value = None
        client = self._client(self.mock_user, None)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$x",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 404)

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_expression_too_long_returns_422(self, mock_get_wf):
        mock_get_wf.return_value = self.mock_workflow
        client = self._client(self.mock_user, self.mock_workflow)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$" + "x" * 10001,
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        }, headers=_auth_headers())
        self.assertIn(resp.status_code, [400, 422])

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_invalid_expression_returns_200_with_error_field(self, mock_get_wf):
        mock_get_wf.return_value = self.mock_workflow
        client = self._client(self.mock_user, self.mock_workflow)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$@@broken@@",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.json()["error"])

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_result_type_array(self, mock_get_wf):
        wf = MagicMock()
        wf.nodes = [{"id": NODE_ID, "data": {"label": "d", "pinnedData": {"items": [1, 2, 3]}}}]
        mock_get_wf.return_value = wf
        client = self._client(self.mock_user, wf)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "$d.items",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["result_type"], "array")
        self.assertTrue(data["preserved_type"])
        self.assertIsInstance(data["result"], list)

    @patch("app.api.expressions.get_workflow_by_id")
    async def test_preserved_type_false_for_template(self, mock_get_wf):
        wf = MagicMock()
        wf.nodes = [{"id": NODE_ID, "data": {"label": "d", "pinnedData": {"name": "Ali"}}}]
        mock_get_wf.return_value = wf
        client = self._client(self.mock_user, wf)
        resp = client.post("/api/expressions/evaluate", json={
            "expression": "Hello $d.name",
            "workflow_id": WORKFLOW_ID,
            "current_node_id": NODE_ID,
        }, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["preserved_type"])
        self.assertEqual(data["result"], "Hello Ali")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3.2: Run tests — confirm they fail (route not registered yet)**

```bash
cd backend && uv run pytest tests/test_expression_evaluator_api.py -v 2>&1 | head -20
```

Expected: `404` or `ImportError` from missing route.

---

## Task 4 — Implement the API route

**Files:**
- Create: `backend/app/api/expressions.py`
- Modify: `backend/app/main.py`

- [ ] **Step 4.1: Create the router**

```python
# backend/app/api/expressions.py
"""FastAPI router for expression evaluation."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.services.expression_evaluator import (
    ExpressionEvaluateResponse,
    ExpressionTooLongError,
    ExpressionEvaluatorService,
    build_eval_context,
)

router = APIRouter()


class CanvasNodeResult(BaseModel):
    """A single node's last-run output as reported by the frontend canvas store."""

    label: str
    output: dict[str, Any] = Field(default_factory=dict)


class ExpressionEvaluateRequest(BaseModel):
    expression: str
    workflow_id: UUID
    current_node_id: str
    field_name: str | None = None
    node_results: list[CanvasNodeResult] = Field(default_factory=list)


async def get_workflow_by_id(
    workflow_id: UUID,
    db: AsyncSession,
    user: User,
) -> Any | None:
    """Load workflow from DB; return None if not found or not owned by user."""
    from app.api.workflows import get_workflow  # noqa: PLC0415 — avoid circular import

    return await get_workflow(db, str(workflow_id), user)


@router.post("/evaluate", response_model=None)
async def evaluate_expression(
    request: ExpressionEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Evaluate an expression or template string against the workflow's pinned / canvas context.

    Returns a structured result with type information. Never raises 5xx for expression
    evaluation errors — those are returned in the `error` field with status 200.
    """
    try:
        workflow = await get_workflow_by_id(request.workflow_id, db, current_user)
    except Exception:
        workflow = None

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    canvas_results = [
        {"label": r.label, "output": r.output} for r in request.node_results
    ]
    context = build_eval_context(
        workflow_nodes=workflow.nodes or [],
        canvas_results=canvas_results,
    )

    svc = ExpressionEvaluatorService()
    try:
        response: ExpressionEvaluateResponse = svc.evaluate(request.expression, context)
    except ExpressionTooLongError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "result": response.result,
        "result_type": response.result_type,
        "preserved_type": response.preserved_type,
        "error": response.error,
    }
```

- [ ] **Step 4.2: Register the router in `main.py`**

In `backend/app/main.py`, add `expressions` to the import block and register it:

```python
# In the from app.api import (...) block, add:
    expressions,
```

```python
# After the existing app.include_router calls, add:
app.include_router(expressions.router, prefix="/api/expressions", tags=["Expressions"])
```

- [ ] **Step 4.3: Run all tests**

```bash
cd backend && uv run pytest tests/test_expression_evaluator_service.py tests/test_expression_evaluator_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 4.4: Run full check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && uv run --directory backend ruff check backend/app/services/expression_evaluator.py backend/app/api/expressions.py
```

Fix any ruff warnings, then:

```bash
cd backend && uv run ruff format app/services/expression_evaluator.py app/api/expressions.py
```

- [ ] **Step 4.5: Commit**

```bash
git add backend/app/services/expression_evaluator.py backend/app/api/expressions.py backend/app/main.py backend/tests/test_expression_evaluator_api.py
git commit -m "feat: add POST /api/expressions/evaluate endpoint with unit tests"
```

---

## Task 5 — Extend existing output template tests

**Files:**
- Modify: `backend/tests/test_output_message_template_resolve.py`

- [ ] **Step 5.1: Add wrapper-consistency cases**

Open `backend/tests/test_output_message_template_resolve.py` and append a new test class at the end:

```python
class TestExpressionEvaluatorServiceConsistency(unittest.TestCase):
    """
    Verify that ExpressionEvaluatorService.evaluate() returns results
    consistent with the executor's own _is_single_dollar_expression branching.
    """

    def _svc(self):
        from app.services.expression_evaluator import ExpressionEvaluatorService
        return ExpressionEvaluatorService()

    def test_single_expr_consistent_with_executor_branch(self):
        from app.services.expression_evaluator import is_single_dollar_expression
        expr = "$node.items"
        self.assertTrue(is_single_dollar_expression(expr))
        resp = self._svc().evaluate(expr, {"node": {"items": [1, 2]}})
        self.assertIsInstance(resp.result, list)

    def test_template_consistent_with_executor_branch(self):
        from app.services.expression_evaluator import is_single_dollar_expression
        expr = "prefix $node.text suffix"
        self.assertFalse(is_single_dollar_expression(expr))
        resp = self._svc().evaluate(expr, {"node": {"text": "hello"}})
        self.assertEqual(resp.result, "prefix hello suffix")
```

- [ ] **Step 5.2: Run**

```bash
cd backend && uv run pytest tests/test_output_message_template_resolve.py -v
```

Expected: all pass.

- [ ] **Step 5.3: Commit**

```bash
git add backend/tests/test_output_message_template_resolve.py
git commit -m "test: add ExpressionEvaluatorService consistency cases"
```

---

## Task 6 — Frontend: add expressionApi to api.ts and workflow types

**Files:**
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/workflow.ts`

- [ ] **Step 6.1: Add types to `workflow.ts`**

Add after the `NodeResult` interface (around line 507):

```typescript
export interface ExpressionEvaluateCanvasResult {
  label: string;
  output: Record<string, unknown>;
}

export interface ExpressionEvaluateRequest {
  expression: string;
  workflow_id: string;
  current_node_id: string;
  field_name?: string;
  node_results: ExpressionEvaluateCanvasResult[];
}

export interface ExpressionEvaluateResponse {
  result: unknown;
  result_type: "string" | "number" | "boolean" | "array" | "object" | "null";
  preserved_type: boolean;
  error: string | null;
}
```

- [ ] **Step 6.2: Add `expressionApi` to `api.ts`**

At the end of `api.ts`, add:

```typescript
import type {
  ExpressionEvaluateRequest,
  ExpressionEvaluateResponse,
} from "@/types/workflow";

export const expressionApi = {
  evaluate: async (request: ExpressionEvaluateRequest): Promise<ExpressionEvaluateResponse> => {
    const response = await api.post<ExpressionEvaluateResponse>(
      "/api/expressions/evaluate",
      request,
    );
    return response.data;
  },
};
```

(Use the same `api` axios instance already defined in that file.)

- [ ] **Step 6.3: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i error | head -20
```

Expected: no new errors.

- [ ] **Step 6.4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/services/api.ts
git commit -m "feat: add ExpressionEvaluateRequest/Response types and expressionApi client"
```

---

## Task 7 — Update ExpressionInput.vue

**Files:**
- Modify: `frontend/src/components/ui/ExpressionInput.vue`

This is the largest single-file change. Follow these steps carefully.

- [ ] **Step 7.1: Remove evaluationMode from Props interface**

Find the `interface Props` block (around line 14). Change:

```typescript
// BEFORE
interface Props {
  // ...
  evaluationMode?: "template" | "expression";
  // ...
}
```

```typescript
// AFTER — keep prop as optional but deprecated; it has no effect
interface Props {
  // ...
  /** @deprecated No longer used. Kept for one release cycle to avoid breaking callers. */
  evaluationMode?: "template" | "expression";
  // ...
}
```

And in `withDefaults`, keep the default but add a `watch` that logs a warning if anything passes it:

```typescript
// After the props definition:
if (import.meta.env.DEV) {
  watch(() => props.evaluationMode, (val) => {
    if (val !== undefined) {
      console.warn(
        '[ExpressionInput] evaluationMode prop is deprecated and has no effect. ' +
        'Remove it from the parent component.'
      );
    }
  }, { immediate: true });
}
```

- [ ] **Step 7.2: Update dialogTitle default to use dialogKeyLabel**

Find the `dialogTitle` prop default and the header rendering. Change the dialog header template to show `"Evaluate — {dialogKeyLabel}"`:

```html
<!-- BEFORE (somewhere in template, the dialog header) -->
<span>{{ props.dialogTitle }}</span>

<!-- AFTER -->
<span>Evaluate{{ props.dialogKeyLabel ? ` — ${props.dialogKeyLabel}` : '' }}</span>
```

Update the `dialogTitle` default to `"Evaluate"`:

```typescript
dialogTitle: "Evaluate",
```

- [ ] **Step 7.3: Enlarge the dialog to 80 vw × 80 vh**

Find the Teleport / dialog container div. Look for classes like `fixed inset-0` or `w-full h-full`. Replace the inner dialog panel sizing:

```html
<!-- BEFORE: full-screen overlay style -->
<div class="fixed inset-0 z-50 flex flex-col bg-background">

<!-- AFTER: centered modal 80vw × 80vh -->
<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
  <div class="relative flex flex-col bg-background rounded-lg shadow-2xl"
       style="width: 80vw; height: 80vh; max-width: 1400px;">
```

Close the new wrapper `</div>` where the original outer div closed.

- [ ] **Step 7.4: Remove all frontend preview computation functions**

Delete the following functions entirely (search by name):
- `resolveTemplatePreview()`
- `resolveExpressionPreview()` (or equivalent)
- `getDialogOutput()` — replace with backend result display (see Step 7.5)
- Arithmetic tokenizer helper (any function that tokenizes `$` for arithmetic preview)
- Ternary split helper (any function named like `splitTernaryExpression`)

Keep:
- `findDollarExpressions()` — still used by autocomplete
- `expressionDollarWarning` computed — keeps syntax warning in place

- [ ] **Step 7.5: Add Run button state and backend call**

Add these refs and the `runExpression` function:

```typescript
import { expressionApi } from "@/services/api";
import type { ExpressionEvaluateResponse } from "@/types/workflow";

const runResult = ref<ExpressionEvaluateResponse | null>(null);
const runLoading = ref(false);
const runError = ref<string | null>(null);

const hasContext = computed((): boolean => {
  // Run is enabled if any upstream node has pinnedData OR there are nodeResults
  const hasPinned = (props.nodes ?? []).some((n) => n.data?.pinnedData);
  const hasResults = (props.nodeResults ?? []).length > 0;
  return hasPinned || hasResults;
});

async function runExpression(): Promise<void> {
  if (!props.currentNodeId) return;
  // workflowStore is already imported in PropertiesPanel; in ExpressionInput,
  // add: import { useWorkflowStore } from "@/stores/workflow"; const workflowStore = useWorkflowStore();
  // Then access the current workflow id:
  const workflowStore = useWorkflowStore();
  const workflowId = workflowStore.currentWorkflow?.id;
  if (!workflowId) return;

  runLoading.value = true;
  runError.value = null;
  runResult.value = null;

  try {
    const canvasResults = (props.nodeResults ?? []).map((r) => ({
      label: r.node_label,
      output: r.output,
    }));

    runResult.value = await expressionApi.evaluate({
      expression: dialogValue.value,
      workflow_id: workflowId,
      current_node_id: props.currentNodeId,
      field_name: props.dialogKeyLabel || undefined,
      node_results: canvasResults,
    });
  } catch (err) {
    runError.value = String(err);
  } finally {
    runLoading.value = false;
  }
}
```

Add `Ctrl/Cmd+R` keyboard shortcut in the dialog keydown handler:

```typescript
if ((e.ctrlKey || e.metaKey) && e.key === "r") {
  e.preventDefault();
  void runExpression();
}
```

- [ ] **Step 7.6: Update Output section template**

Replace the output preview section (previously showed `dialogOutput` computed from frontend) with:

```html
<!-- Output section -->
<div class="flex flex-col gap-2 p-3 border-t">
  <div class="flex items-center justify-between">
    <span class="text-xs font-medium text-muted-foreground uppercase tracking-wide">Output</span>
    <button
      type="button"
      :disabled="!hasContext || runLoading"
      :title="hasContext ? 'Run (Ctrl+R)' : 'Pin node data or run the workflow first'"
      class="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium
             bg-primary text-primary-foreground
             disabled:opacity-40 disabled:cursor-not-allowed
             hover:bg-primary/90 transition-colors"
      @click="runExpression"
    >
      <span v-if="runLoading">...</span>
      <span v-else>▶ Run</span>
    </button>
  </div>

  <!-- Error state -->
  <div v-if="runError" class="rounded bg-destructive/10 p-2 text-xs text-destructive">
    {{ runError }}
  </div>

  <!-- Result from backend -->
  <template v-else-if="runResult">
    <div v-if="runResult.error" class="rounded bg-destructive/10 p-2 text-xs text-destructive">
      {{ runResult.error }}
    </div>
    <template v-else>
      <!-- Path picker when result is object/array -->
      <ExpressionOutputPathPicker
        v-if="runResult.result_type === 'array' || runResult.result_type === 'object'"
        :data="runResult.result"
        :dialog-value="dialogValue"
        @pick="handlePathPick"
      />
      <!-- Primitive result -->
      <div v-else class="rounded bg-muted p-2 text-xs font-mono break-all">
        {{ runResult.result ?? 'null' }}
      </div>
      <div class="text-xs text-muted-foreground">
        Type: <span class="font-medium">{{ runResult.result_type }}</span>
        <span v-if="runResult.preserved_type" class="ml-2 text-green-600">(type preserved)</span>
      </div>
    </template>
  </template>

  <!-- Empty state -->
  <div v-else class="text-xs text-muted-foreground italic">
    Press Run to evaluate
  </div>
</div>
```

- [ ] **Step 7.7: Typecheck and lint**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i error | head -20
bun run lint 2>&1 | head -20
```

Fix any errors.

- [ ] **Step 7.8: Commit**

```bash
git add frontend/src/components/ui/ExpressionInput.vue
git commit -m "feat: unify ExpressionInput — Run button, backend eval, Evaluate header, 80vw modal"
```

---

## Task 8 — Remove evaluation-mode from PropertiesPanel.vue

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

There are ~50 occurrences of `evaluation-mode="template"` and `evaluation-mode="expression"`.

- [ ] **Step 8.1: Remove all evaluation-mode attributes**

```bash
cd frontend && grep -n 'evaluation-mode' src/components/Panels/PropertiesPanel.vue | wc -l
```

Use sed or find-replace in editor to remove ALL occurrences of:
- `evaluation-mode="template"`
- `evaluation-mode="expression"`
- `:evaluation-mode="..."`

```bash
# Remove all evaluation-mode attributes (the prop is deprecated and ignored)
sed -i '' 's/ evaluation-mode="template"//g; s/ evaluation-mode="expression"//g; s/ :evaluation-mode="[^"]*"//g' \
  src/components/Panels/PropertiesPanel.vue
```

- [ ] **Step 8.2: Verify count is zero**

```bash
grep -c 'evaluation-mode' frontend/src/components/Panels/PropertiesPanel.vue
```

Expected: `0`

- [ ] **Step 8.3: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i error | head -20
```

- [ ] **Step 8.4: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "refactor: remove all evaluation-mode attributes from PropertiesPanel"
```

---

## Task 9 — Remove evaluationMode from JsonInputPanel.vue

**Files:**
- Modify: `frontend/src/components/ui/JsonInputPanel.vue`

- [ ] **Step 9.1: Remove evaluationMode prop forwarding**

Open the file, find any `evaluationMode` prop definition and any place it forwards it to `ExpressionInput`. Remove both the prop declaration and the binding.

- [ ] **Step 9.2: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i error | head -10
```

- [ ] **Step 9.3: Commit**

```bash
git add frontend/src/components/ui/JsonInputPanel.vue
git commit -m "refactor: remove evaluationMode prop from JsonInputPanel"
```

---

## Task 10 — Update DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 10.1: Remove template vs expression mode distinction from prompt**

Search for any mention of "template mode", "expression mode", "Text(String) Mode", "evaluationMode" in `WORKFLOW_DSL_SYSTEM_PROMPT`.

Find the relevant section and replace with:

```python
# In WORKFLOW_DSL_SYSTEM_PROMPT, find any passage about field modes and replace with:
"""
## Expression Fields

All node data string fields use unified expression syntax. The backend automatically
determines evaluation semantics from the string content:

- **Single expression** (entire value is one `$expr`): The native type is preserved.
  Arrays remain arrays, objects remain objects. Example: `"$llm.items"` → returns list.
- **Template** (prose with embedded `$refs`): Result is always a string.
  Example: `"Hello $user.name, here is $llm.text"` → returns concatenated string.
- **Literal** (no `$`): Returned as-is.

The `$` placement rules remain unchanged (one `$` at start, never inside parentheses).
"""
```

- [ ] **Step 10.2: Run ruff + format**

```bash
cd backend && uv run ruff check app/services/workflow_dsl_prompt.py && uv run ruff format app/services/workflow_dsl_prompt.py
```

- [ ] **Step 10.3: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "docs: update AI DSL prompt — remove template/expression mode distinction"
```

---

## Task 11 — Update documentation

**Files:**
- Modify: `frontend/src/docs/content/reference/expression-evaluation-dialog.md`
- Modify: `frontend/src/docs/content/reference/expression-dsl.md`

Use the `heym-documentation` skill for this task.

- [ ] **Step 11.1: Rewrite expression-evaluation-dialog.md**

Replace the "Expression Mode" / "Template Mode" sections under "Output Section" with:

```markdown
## Output Section

The dialog shows a live preview when you press the **Run** button (or `Ctrl`/`Cmd` + `R`).

### Evaluation

| Expression type | Result |
|---|---|
| Single `$expr` (entire field) | Typed value — arrays stay arrays, objects stay objects |
| Text with embedded `$refs` | String — each `$ref` substituted, concatenated |
| Literal text (no `$`) | Returned as-is |

**Examples:**

| Input | Result |
|---|---|
| `$input.items` | `[1, 2, 3]` (list preserved) |
| `Hello $input.name` | `"Hello John"` |
| `$input.count + 1` | `6` |
| `just text` | `"just text"` |

### Run button

Click **Run** (or press `Ctrl`/`Cmd` + `R`) to evaluate the expression against the workflow's current context:
- **Pinned data** (set via the canvas Pin button) takes priority.
- **Last run outputs** (available after running the workflow on the canvas) fill remaining nodes.
- If neither is available, the button shows a tooltip: *"Pin node data or run the workflow first"*.
```

Remove the "Expression Mode" / "Text(String) Mode" badge description entirely. Remove the "Opening the Dialog" section reference to "double-click" if it is node-type-specific (keep generic description).

- [ ] **Step 11.2: Add type-preservation note to expression-dsl.md**

After the "Literals" section, add:

```markdown
## Type Preservation

When the **entire** field value is a single `$expr`, the native type is preserved:

- `$node.items` → `[1, 2, 3]` (array, not a JSON string)
- `$node.meta` → `{"key": "val"}` (object, not a JSON string)
- `$node.active` → `true` (boolean)

When a `$expr` appears inside a larger string (template), the result is always a string:

- `Count: $node.count` → `"Count: 5"`
```

- [ ] **Step 11.3: Commit**

```bash
git add frontend/src/docs/content/reference/expression-evaluation-dialog.md \
        frontend/src/docs/content/reference/expression-dsl.md
git commit -m "docs: update expression dialog and DSL docs for unified evaluator"
```

---

## Task 12 — Final check

- [ ] **Step 12.1: Run full backend test suite**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./run_tests.sh
```

Expected: all tests pass, no regressions.

- [ ] **Step 12.2: Run frontend checks**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: zero errors.

- [ ] **Step 12.3: Run ./check.sh**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh
```

Expected: all green.

- [ ] **Step 12.4: Verify success criteria from spec**

```bash
# Should return 0 matches (excluding deprecated comment):
grep -r 'evaluationMode\|evaluation-mode' frontend/src/components --include='*.vue' | grep -v '@deprecated' | grep -v 'warn'

# Should return 0 matches:
grep -r 'resolveTemplatePreview\|resolveExpressionPreview' frontend/src
```

- [ ] **Step 12.5: Final commit**

```bash
git add -A
git commit -m "feat: unified expression evaluator — migration complete"
```

---

## Quick Reference — Key Commands

```bash
# Run new tests only
cd backend && uv run pytest tests/test_expression_evaluator_service.py tests/test_expression_evaluator_api.py -v

# Run all backend tests
./run_tests.sh

# Frontend checks
cd frontend && bun run typecheck && bun run lint

# Full check
./check.sh

# Format backend
cd backend && uv run ruff format .
```
