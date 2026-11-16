import os
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

import httpx

from app.services.workflow_executor import WorkflowExecutor


def _make_branch_merge_workflow(action: str) -> tuple[list[dict], list[dict], dict]:
    nodes = [
        {
            "id": "in1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "set1",
            "type": "set",
            "data": {
                "label": "tradingAgent",
                "mappings": [{"key": "action", "value": action}],
            },
        },
        {
            "id": "cond1",
            "type": "condition",
            "data": {
                "label": "checkTradeAction",
                "condition": '$tradingAgent.action == "buy" || $tradingAgent.action == "sell"',
            },
        },
        {
            "id": "true1",
            "type": "set",
            "data": {
                "label": "sendTradeNotification",
                "mappings": [{"key": "status", "value": "notified"}],
            },
        },
        {
            "id": "merge1",
            "type": "set",
            "data": {
                "label": "updateBalance",
                "mappings": [{"key": "status", "value": "merged"}],
            },
        },
        {
            "id": "out1",
            "type": "output",
            "data": {"label": "finalOut", "message": "$updateBalance.status"},
        },
    ]
    edges = [
        {"id": "e1", "source": "in1", "target": "set1"},
        {"id": "e2", "source": "set1", "target": "cond1"},
        {"id": "e3", "source": "cond1", "target": "true1", "sourceHandle": "true"},
        {"id": "e4", "source": "cond1", "target": "merge1", "sourceHandle": "false"},
        {"id": "e5", "source": "true1", "target": "merge1"},
        {"id": "e6", "source": "merge1", "target": "out1"},
    ]
    initial_inputs = {"headers": {}, "query": {}, "body": {"text": "hi"}}
    return nodes, edges, initial_inputs


def _make_loop_done_workflow() -> tuple[list[dict], list[dict], dict]:
    nodes = [
        {
            "id": "in1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "set1",
            "type": "set",
            "data": {
                "label": "prepareTargets",
                "mappings": [{"key": "websites", "value": "$array('a').add('b')"}],
            },
        },
        {
            "id": "var1",
            "type": "variable",
            "data": {
                "label": "initResults",
                "variableName": "evaluationResults",
                "variableValue": "$array()",
                "variableType": "array",
            },
        },
        {
            "id": "loop1",
            "type": "loop",
            "data": {"label": "siteLoop", "arrayExpression": "$prepareTargets.websites"},
        },
        {
            "id": "set2",
            "type": "set",
            "data": {
                "label": "evaluateSite",
                "mappings": [{"key": "url", "value": "$siteLoop.item"}],
            },
        },
        {
            "id": "var2",
            "type": "variable",
            "data": {
                "label": "collectResult",
                "variableName": "evaluationResults",
                "variableValue": "$vars.evaluationResults.add(evaluateSite)",
                "variableType": "array",
            },
        },
        {
            "id": "set3",
            "type": "set",
            "data": {
                "label": "doneSummary",
                "mappings": [
                    {"key": "branch", "value": "$siteLoop.branch"},
                    {"key": "resultsLength", "value": "$siteLoop.results.length"},
                    {"key": "collectedLength", "value": "$vars.evaluationResults.length"},
                ],
            },
        },
    ]
    edges = [
        {"id": "e1", "source": "in1", "target": "set1"},
        {"id": "e2", "source": "set1", "target": "var1"},
        {"id": "e3", "source": "var1", "target": "loop1"},
        {"id": "e4", "source": "loop1", "target": "set2", "sourceHandle": "loop"},
        {"id": "e5", "source": "set2", "target": "var2"},
        {"id": "e6", "source": "var2", "target": "loop1", "targetHandle": "loop"},
        {"id": "e7", "source": "loop1", "target": "set3", "sourceHandle": "done"},
    ]
    initial_inputs = {"headers": {}, "query": {}, "body": {"text": "hi"}}
    return nodes, edges, initial_inputs


class WorkflowExecutorBranchingTests(unittest.TestCase):
    def _execute(self, action: str) -> dict[str, dict]:
        nodes, edges, initial_inputs = _make_branch_merge_workflow(action)
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=initial_inputs)
        self.assertEqual(result.status, "success")
        return {row["node_label"]: row for row in result.node_results}

    def test_false_branch_keeps_shared_merge_node_active(self) -> None:
        results = self._execute("hold")

        self.assertEqual(results["checkTradeAction"]["output"]["branch"], "false")
        self.assertEqual(results["sendTradeNotification"]["status"], "skipped")
        self.assertEqual(results["updateBalance"]["status"], "success")
        self.assertEqual(results["updateBalance"]["output"]["status"], "merged")
        self.assertEqual(results["finalOut"]["status"], "success")
        self.assertEqual(results["finalOut"]["output"]["result"], "merged")

    def test_true_branch_keeps_shared_merge_node_active(self) -> None:
        results = self._execute("buy")

        self.assertEqual(results["checkTradeAction"]["output"]["branch"], "true")
        self.assertEqual(results["sendTradeNotification"]["status"], "success")
        self.assertEqual(results["updateBalance"]["status"], "success")
        self.assertEqual(results["updateBalance"]["output"]["status"], "merged")
        self.assertEqual(results["finalOut"]["status"], "success")
        self.assertEqual(results["finalOut"]["output"]["result"], "merged")

    def test_condition_treats_missing_source_handle_as_true_branch(self) -> None:
        nodes = [
            {
                "id": "input_1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "condition_1",
                "type": "condition",
                "data": {"label": "condition", "condition": '$userInput.body.text == "as"'},
            },
            {
                "id": "success_1",
                "type": "output",
                "data": {"label": "successBranch", "message": "$userInput.body.text.upper()"},
            },
            {
                "id": "error_1",
                "type": "output",
                "data": {"label": "errorBranch", "message": "false branch"},
            },
        ]
        edges = [
            {"id": "e1", "source": "input_1", "target": "condition_1", "targetHandle": "input"},
            {"id": "e2", "source": "condition_1", "target": "success_1"},
            {
                "id": "e3",
                "source": "condition_1",
                "target": "error_1",
                "sourceHandle": "false",
                "targetHandle": "input",
            },
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )
        results = {row["node_label"]: row for row in result.node_results}

        self.assertEqual(result.status, "success")
        self.assertEqual(results["condition"]["output"]["branch"], "false")
        self.assertEqual(results["successBranch"]["status"], "skipped")
        self.assertEqual(results["errorBranch"]["status"], "success")
        self.assertEqual(result.outputs, {"errorBranch": {"result": "false branch"}})

    def test_false_branch_loop_back_waits_before_next_iteration(self) -> None:
        nodes = [
            {
                "id": "input_1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "set_1",
                "type": "set",
                "data": {
                    "label": "prepareItems",
                    "mappings": [{"key": "items", "value": "$array(true).add(false).add(true)"}],
                },
            },
            {
                "id": "loop_1",
                "type": "loop",
                "data": {"label": "loop", "arrayExpression": "$prepareItems.items"},
            },
            {
                "id": "condition_1",
                "type": "condition",
                "data": {"label": "isValid", "condition": "$loop.item"},
            },
            {
                "id": "wait_1",
                "type": "wait",
                "data": {"label": "pauseFalse", "duration": 25},
            },
        ]
        edges = [
            {"id": "e1", "source": "input_1", "target": "set_1"},
            {"id": "e2", "source": "set_1", "target": "loop_1"},
            {"id": "e3", "source": "loop_1", "target": "condition_1", "sourceHandle": "loop"},
            {"id": "e4", "source": "condition_1", "target": "loop_1", "targetHandle": "loop"},
            {
                "id": "e5",
                "source": "condition_1",
                "target": "wait_1",
                "sourceHandle": "false",
            },
            {"id": "e6", "source": "wait_1", "target": "loop_1", "targetHandle": "loop"},
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "start"}},
        )

        self.assertEqual(result.status, "success")
        pause_sequence = next(
            row["metadata"]["sequence"]
            for row in result.node_results
            if row["node_label"] == "pauseFalse"
        )
        third_loop_sequence = next(
            row["metadata"]["sequence"]
            for row in result.node_results
            if row["node_label"] == "loop"
            and row["output"].get("branch") == "loop"
            and row["output"].get("index") == 2
        )
        self.assertGreater(third_loop_sequence, pause_sequence)

    def test_true_branch_loop_back_does_not_execute_false_branch(self) -> None:
        nodes = [
            {
                "id": "input_1",
                "type": "textInput",
                "data": {"label": "dataTable", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "loop_1",
                "type": "loop",
                "data": {"label": "loop", "arrayExpression": "$dataTable.body.rows"},
            },
            {
                "id": "condition_1",
                "type": "condition",
                "data": {
                    "label": "usernameRepoValid",
                    "condition": "$loop.item.data.targetRepo.contains($loop.item.data.username)",
                },
            },
            {
                "id": "update_1",
                "type": "set",
                "data": {
                    "label": "dataTable1",
                    "mappings": [{"key": "rowId", "value": "$loop.item.id"}],
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "input_1", "target": "loop_1"},
            {"id": "e2", "source": "loop_1", "target": "condition_1", "sourceHandle": "loop"},
            {
                "id": "e3",
                "source": "condition_1",
                "target": "update_1",
                "sourceHandle": "false",
            },
            {"id": "e4", "source": "update_1", "target": "loop_1", "targetHandle": "loop"},
            {
                "id": "e5",
                "source": "condition_1",
                "target": "loop_1",
                "sourceHandle": "true",
                "targetHandle": "loop",
            },
        ]
        rows = [
            {
                "id": "invalid-1",
                "data": {"targetRepo": "acme-corp/analytics-app", "username": "user-beta"},
            },
            {
                "id": "valid-1",
                "data": {"targetRepo": "user-gamma/widget-repo", "username": "user-gamma"},
            },
            {
                "id": "valid-2",
                "data": {"targetRepo": "user-delta/sample-project", "username": "user-delta"},
            },
            {
                "id": "invalid-2",
                "data": {"targetRepo": "research-lab/agent-toolkit", "username": "user-zeta"},
            },
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"rows": rows, "text": "start"}},
        )

        self.assertEqual(result.status, "success")
        condition_branches = [
            row["output"]["branch"]
            for row in result.node_results
            if row["node_label"] == "usernameRepoValid" and row["status"] == "success"
        ]
        updated_row_ids = [
            row["output"]["rowId"]
            for row in result.node_results
            if row["node_label"] == "dataTable1" and row["status"] == "success"
        ]
        self.assertEqual(condition_branches, ["false", "true", "true", "false"])
        self.assertEqual(updated_row_ids, ["invalid-1", "invalid-2"])

    def test_error_branch_preserves_output_reached_by_parallel_branch(self) -> None:
        nodes = [
            {
                "id": "input_1",
                "type": "textInput",
                "data": {"label": "start", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "watch_1",
                "type": "mcpCall",
                "data": {
                    "label": "watch",
                    "connection": {
                        "id": "conn_1",
                        "transport": "sse",
                        "url": "http://localhost:3000/sse",
                        "timeoutSeconds": 30,
                    },
                    "selectedTool": "",
                    "toolArguments": {},
                    "onErrorEnabled": True,
                },
            },
            {
                "id": "star_1",
                "type": "wait",
                "data": {"label": "star", "duration": 10},
            },
            {
                "id": "output_1",
                "type": "output",
                "data": {"label": "searchResult", "message": "$star.body.text"},
            },
        ]
        edges = [
            {"id": "e1", "source": "input_1", "target": "watch_1"},
            {"id": "e2", "source": "input_1", "target": "star_1"},
            {"id": "e3", "source": "watch_1", "target": "output_1", "sourceHandle": "output"},
            {"id": "e4", "source": "star_1", "target": "output_1", "sourceHandle": "output"},
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )
        results = {row["node_label"]: row for row in result.node_results}

        self.assertEqual(result.status, "success")
        self.assertEqual(results["watch"]["status"], "success")
        self.assertTrue(results["watch"]["output"]["_errorBranch"])
        self.assertEqual(results["star"]["status"], "success")
        self.assertEqual(results["searchResult"]["status"], "success")
        self.assertEqual(result.outputs, {"searchResult": {"result": "hello"}})

    def test_http_success_skips_error_handle_branch(self) -> None:
        nodes = [
            {
                "id": "http_1",
                "type": "http",
                "data": {
                    "label": "httpRequest",
                    "curl": "curl -X GET https://example.test/health",
                    "onErrorEnabled": True,
                },
            },
            {
                "id": "success_1",
                "type": "output",
                "data": {"label": "success", "message": "$httpRequest.status"},
            },
            {
                "id": "error_1",
                "type": "output",
                "data": {"label": "errorBranch", "message": "$httpRequest"},
            },
        ]
        edges = [
            {
                "id": "e1",
                "source": "http_1",
                "target": "success_1",
                "sourceHandle": "output",
                "targetHandle": "input",
            },
            {
                "id": "e2",
                "source": "http_1",
                "target": "error_1",
                "sourceHandle": "error",
                "targetHandle": "input",
            },
        ]
        request = httpx.Request("GET", "https://example.test/health")
        response = httpx.Response(200, json={"status": "healthy"}, request=request)

        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client") as mock_get_client,
        ):
            mock_get_client.return_value.request.return_value = response
            executor = WorkflowExecutor(nodes=nodes, edges=edges)

            result = executor.execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {}},
            )

        results = {row["node_label"]: row for row in result.node_results}

        self.assertEqual(result.status, "success")
        self.assertEqual(results["httpRequest"]["status"], "success")
        self.assertEqual(results["httpRequest"]["output"]["status"], 200)
        self.assertEqual(results["success"]["status"], "success")
        self.assertEqual(results["success"]["output"], {"result": 200})
        self.assertEqual(results["errorBranch"]["status"], "skipped")
        self.assertEqual(result.outputs, {"success": {"result": 200}})

    def test_loop_done_branch_waits_for_loop_done_output(self) -> None:
        nodes, edges, initial_inputs = _make_loop_done_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=initial_inputs)

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.outputs["doneSummary"],
            {"branch": "done", "resultsLength": 2, "collectedLength": 2},
        )

        loop_results = [
            row
            for row in result.node_results
            if row["node_label"] == "siteLoop" and row["status"] == "success"
        ]
        self.assertEqual(
            [row["output"]["branch"] for row in loop_results], ["loop", "loop", "done"]
        )

        done_summary_results = [
            row
            for row in result.node_results
            if row["node_label"] == "doneSummary" and row["status"] == "success"
        ]
        self.assertEqual(len(done_summary_results), 1)
        self.assertEqual(
            done_summary_results[0]["output"],
            {"branch": "done", "resultsLength": 2, "collectedLength": 2},
        )


class TestConditionEvalRejectsDunderTraversal(unittest.TestCase):
    """Regression test for security advisory GHSA-pm6h-x3h5-j38h, finding C1.

    The condition evaluator must NOT execute Python attribute traversal. Payloads
    that reach `object.__subclasses__()` via any Python type's `__class__.__bases__`
    must raise rather than execute. Before the fix, `eval()` with `__builtins__: {}`
    was used and the subclasses gadget achieved RCE.

    Note: the simpler `len.__init__.__globals__` payload does NOT fire because
    builtin slot wrappers have no `__globals__` — only the subclasses gadget works.
    The maintainer confirmed this during review.
    """

    DUNDER_PAYLOADS = [
        # The verified RCE gadget — subclasses traversal to reach __import__.
        "str.__class__.__bases__[0].__subclasses__()",
        '"".__class__.__bases__[0].__subclasses__()',
        "[].__class__.__mro__",
        # Realistic attack shape: legitimate-looking condition with traversal after `or`.
        # Left side must be False so simpleeval actually evaluates the right side
        # (Python `or` short-circuits — if left is True, right is never evaluated
        # and the dunder traversal never fires).
        "$input.x == 999 or (str.__class__.__bases__[0].__subclasses__())",
        # Format-string escape via __class__.
        '"{0.__class__.__bases__[0].__subclasses__}".format("")',
    ]

    def _make_executor(self) -> WorkflowExecutor:
        # Constructor signature: WorkflowExecutor(nodes=..., edges=...)
        # See test_workflow_executor_branching.py:144 for the established pattern.
        return WorkflowExecutor(nodes=[], edges=[])

    def test_payloads_raise(self) -> None:
        executor = self._make_executor()
        for payload in self.DUNDER_PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(Exception, msg=f"Payload should have raised: {payload}"):
                    # evaluate_condition_strict propagates the underlying error.
                    # evaluate_condition swallows it and returns False, which is also
                    # safe, but we want to assert the eval path itself rejects.
                    executor.evaluate_condition_strict(payload, {"input": {"x": 1}}, None)

    def test_normal_conditions_still_work(self) -> None:
        """Make sure the fix doesn't break legitimate condition evaluation."""
        executor = self._make_executor()
        self.assertTrue(
            executor.evaluate_condition_strict(
                '$tradingAgent.action == "buy"',
                {"tradingAgent": {"action": "buy"}},
                None,
            )
        )
        self.assertFalse(
            executor.evaluate_condition_strict(
                '$tradingAgent.action == "sell"',
                {"tradingAgent": {"action": "buy"}},
                None,
            )
        )
        self.assertTrue(
            executor.evaluate_condition_strict(
                '$tradingAgent.action == "buy" || $tradingAgent.action == "sell"',
                {"tradingAgent": {"action": "sell"}},
                None,
            )
        )
        self.assertTrue(
            executor.evaluate_condition_strict(
                "$node.count > 5",
                {"node": {"count": 10}},
                None,
            )
        )

    def test_js_style_literal_aliases_still_work(self) -> None:
        """simpleeval doesn't recognise `true`/`false`/`null`/`undefined` as Python
        literals — they must be passed via `names`. Regression for the maintainer's
        feedback that `names={}` breaks `$x == true` with NameNotDefined.
        """
        executor = self._make_executor()
        self.assertTrue(
            executor.evaluate_condition_strict(
                "$node.active == true",
                {"node": {"active": True}},
                None,
            )
        )
        self.assertFalse(
            executor.evaluate_condition_strict(
                "$node.active == false",
                {"node": {"active": True}},
                None,
            )
        )
        self.assertTrue(
            executor.evaluate_condition_strict(
                "$node.value == null",
                {"node": {"value": None}},
                None,
            )
        )
        self.assertTrue(
            executor.evaluate_condition_strict(
                "$node.value == undefined",
                {"node": {"value": None}},
                None,
            )
        )


class TestExpressionEvalRejectsDotListAndFallbackSandboxEscape(unittest.TestCase):
    """Regression for GHSA-87x2-9jwx-7gh4.

    simpleeval hardening from GHSA-pm6h covers condition/substitution, but DotList
    item expressions and the simpleeval fallback resolver walked dunders with raw
    getattr. These tests pin the three PoC expressions and keep ``_id`` dict keys
    working.
    """

    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_map_dunder_path_does_not_return_bound_method(self) -> None:
        executor = self._executor()
        result = executor.resolve_expression(
            '$arr.map("item.__class__.__base__.__subclasses__")',
            {"arr": ["x"]},
            preserve_type=True,
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertFalse(callable(result[0]))
        self.assertNotIsInstance(result[0], type)
        self.assertIsNone(result[0])

    def test_calling_mapped_dunder_method_does_not_list_subclasses(self) -> None:
        executor = self._executor()
        mapped = executor.resolve_expression(
            '$arr.map("item.__class__.__base__.__subclasses__")[0]',
            {"arr": ["x"]},
            preserve_type=True,
        )
        result = executor.resolve_expression("$m()", {"m": mapped}, preserve_type=True)
        if isinstance(result, (list, tuple)) and result:
            self.assertFalse(
                all(isinstance(item, type) for item in result),
                f"Bound-method call returned loaded classes: {result!r}",
            )
        else:
            self.assertFalse(callable(result))

    def test_init_globals_os_system_does_not_execute(self) -> None:
        class _Probe:
            def __init__(self) -> None:
                pass

        fd, marker = tempfile.mkstemp(prefix="heym_expr_rce_reg_")
        os.close(fd)
        os.unlink(marker)
        try:
            payload = f'$p.__init__.__globals__["os"].system("touch {marker}")'
            result = self._executor().resolve_expression(
                payload,
                {"p": _Probe},
                preserve_type=True,
            )
            self.assertFalse(
                os.path.exists(marker),
                f"PoC executed; marker created, result={result!r}",
            )
            self.assertNotEqual(result, 0)
        finally:
            if os.path.exists(marker):
                os.unlink(marker)

    def test_underscore_prefixed_dict_keys_still_resolve(self) -> None:
        executor = self._executor()
        self.assertEqual(
            executor.resolve_expression(
                "$item._id",
                {"item": {"_id": "abc-123"}},
                preserve_type=True,
            ),
            "abc-123",
        )
        self.assertEqual(
            executor.resolve_expression(
                '$arr.map("item._id")',
                {"arr": [{"_id": "a"}, {"_id": "b"}]},
                preserve_type=True,
            ),
            ["a", "b"],
        )
        self.assertEqual(
            executor.resolve_expression(
                '$arr.distinctBy("item._id").map("item._id")',
                {"arr": [{"_id": "a"}, {"_id": "a"}, {"_id": "b"}]},
                preserve_type=True,
            ),
            ["a", "b"],
        )

    def test_legitimate_map_item_id_still_works(self) -> None:
        result = self._executor().resolve_expression(
            '$arr.map("item.id")',
            {"arr": [{"id": 1}, {"id": 2}]},
            preserve_type=True,
        )
        self.assertEqual(result, [1, 2])


class TestGuardedItemExpressionHelpers(unittest.TestCase):
    """Per-helper coverage for GHSA-87x2-9jwx-7gh4 so each guarded path stays pinned."""

    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_every_item_expression_helper_rejects_private_paths(self) -> None:
        executor = self._executor()
        cases = [
            '$arr.map("item.__class__")',
            '$arr.filter("item.__class__")',
            '$arr.sort("item.__class__")',
            '$arr.distinctBy("item.__class__")',
            "$arr.map(\"concat('item.__class__', '')\")",
            "$arr.map(\"get(item, '__class__')\")",
        ]
        for expression in cases:
            with self.subTest(expression=expression):
                result = executor.resolve_expression(expression, {"arr": ["x"]}, preserve_type=True)
                for item in result if isinstance(result, list) else [result]:
                    self.assertNotIsInstance(item, type)
                    self.assertFalse(callable(item))

    def test_get_helper_hides_inherited_builtin_callables(self) -> None:
        executor = self._executor()
        self.assertEqual(
            executor.resolve_expression(
                "$arr.map(\"get(item, 'pop')\")", {"arr": [[1, 2]]}, preserve_type=True
            ),
            [None],
        )
        self.assertEqual(
            executor.resolve_expression(
                "$arr.map(\"get(item, 'name')\")",
                {"arr": [{"name": "bob"}]},
                preserve_type=True,
            ),
            ["bob"],
        )

    def test_node_output_never_carries_a_method_reference(self) -> None:
        # The repr of a bound method leaks a heap address into execution history.
        executor = self._executor()
        for expression, context in (
            ("$s.upper", {"s": "ab"}),
            ("$arr.pop", {"arr": [1, 2]}),
            ("$len", {}),
        ):
            with self.subTest(expression=expression):
                self.assertIsNone(executor.resolve_expression(expression, context))

    def test_documented_expression_api_is_unchanged(self) -> None:
        executor = self._executor()
        cases: list[tuple[str, dict, object]] = [
            ("$s.upper()", {"s": "ab"}, "AB"),
            ("$arr.count(1)", {"arr": [1, 1]}, 2),
            ("$arr.index(2)", {"arr": [1, 2]}, 1),
            ('$arr.join("-")', {"arr": ["a", "b"]}, "a-b"),
            ("$doc._id", {"doc": {"_id": "x"}}, "x"),
            ("$now.year", {}, datetime.now().year),
        ]
        for expression, context, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(executor.resolve_expression(expression, context), expected)

    def test_get_helper_filters_callable_dictionary_values(self) -> None:
        self.assertEqual(
            self._executor().resolve_expression(
                "$arr.map(\"get(item, 'f')\")", {"arr": [{"f": len}]}, preserve_type=True
            ),
            [None],
        )

    def test_public_item_paths_and_helpers_still_work(self) -> None:
        executor = self._executor()
        self.assertEqual(
            executor.resolve_expression(
                '$arr.sort("item.n")', {"arr": [{"n": 2}, {"n": 1}]}, preserve_type=True
            ),
            [{"n": 1}, {"n": 2}],
        )
        self.assertEqual(
            executor.resolve_expression(
                '$arr.filter("item.ok")',
                {"arr": [{"ok": True}, {"ok": False}]},
                preserve_type=True,
            ),
            [{"ok": True}],
        )
        self.assertEqual(
            executor.resolve_expression(
                "$arr.map(\"concat('item.name', '!')\")",
                {"arr": [{"name": "bob"}]},
                preserve_type=True,
            ),
            ["bob!"],
        )


if __name__ == "__main__":
    unittest.main()


class NestedLoopTests(unittest.TestCase):
    """An inner Loop starts over for every item of the outer Loop."""

    ROWS = [[1, 2], [3, 4, 5], [6]]

    def _workflow(self) -> tuple[list[dict], list[dict]]:
        def edge(source: str, target: str, sh: str | None = None, th: str | None = None) -> dict:
            row = {"id": f"{source}-{target}-{sh}-{th}", "source": source, "target": target}
            if sh:
                row["sourceHandle"] = sh
            if th:
                row["targetHandle"] = th
            return row

        nodes = [
            {"id": "in", "type": "textInput", "data": {"label": "userInput"}},
            {
                "id": "outer",
                "type": "loop",
                "data": {"label": "outer", "arrayExpression": "$userInput.body.rows"},
            },
            {
                "id": "inner",
                "type": "loop",
                "data": {"label": "inner", "arrayExpression": "$outer.item"},
            },
            {
                "id": "collect",
                "type": "set",
                "data": {"label": "collect", "mappings": [{"key": "item", "value": "$inner.item"}]},
            },
            {
                "id": "rowDone",
                "type": "set",
                "data": {"label": "rowDone", "mappings": [{"key": "row", "value": "$outer.index"}]},
            },
            {"id": "o", "type": "output", "data": {"label": "out", "message": "done"}},
        ]
        edges = [
            edge("in", "outer"),
            edge("outer", "inner", "loop"),
            edge("inner", "collect", "loop"),
            edge("collect", "inner", None, "loop"),
            edge("inner", "rowDone", "done"),
            edge("rowDone", "outer", None, "loop"),
            edge("outer", "o", "done"),
        ]
        return nodes, edges

    @staticmethod
    def _collected(node_results: list[dict]) -> list[object]:
        return [
            row["output"]["item"]
            for row in node_results
            if row["node_label"] == "collect" and row["status"] == "success"
        ]

    def test_every_inner_item_of_every_row_runs_once(self) -> None:
        nodes, edges = self._workflow()
        result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"rows": self.ROWS}},
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(self._collected(result.node_results), [1, 2, 3, 4, 5, 6])
        row_done = [
            r
            for r in result.node_results
            if r["node_label"] == "rowDone" and r["status"] == "success"
        ]
        self.assertEqual([r["output"]["row"] for r in row_done], [0, 1, 2])

    def test_the_streaming_run_restarts_the_inner_loop_too(self) -> None:
        from app.services.workflow_executor import execute_workflow_streaming

        nodes, edges = self._workflow()
        collected = [
            (event.get("output") or {}).get("item")
            for event in execute_workflow_streaming(
                workflow_id=uuid.uuid4(),
                nodes=nodes,
                edges=edges,
                inputs={"headers": {}, "query": {}, "body": {"rows": self.ROWS}},
            )
            if event.get("type") == "node_complete"
            and event.get("node_label") == "collect"
            and event.get("status") == "success"
        ]

        self.assertEqual(collected, [1, 2, 3, 4, 5, 6])


class LoopErrorHandleRoutingTests(unittest.TestCase):
    """Inside a Loop, each item takes only the success or the error handle of its node."""

    def test_each_item_takes_one_handle(self) -> None:
        def edge(source: str, target: str, sh: str | None = None, th: str | None = None) -> dict:
            row = {"id": f"{source}-{target}-{sh}-{th}", "source": source, "target": target}
            if sh:
                row["sourceHandle"] = sh
            if th:
                row["targetHandle"] = th
            return row

        nodes = [
            {"id": "in", "type": "textInput", "data": {"label": "userInput"}},
            {
                "id": "lp",
                "type": "loop",
                "data": {"label": "items", "arrayExpression": "$userInput.body.urls"},
            },
            {
                "id": "h",
                "type": "http",
                "data": {
                    "label": "fetch",
                    "curl": "curl -X GET $items.item",
                    "onErrorEnabled": True,
                },
            },
            {
                "id": "ok",
                "type": "set",
                "data": {
                    "label": "saveResult",
                    "mappings": [{"key": "url", "value": "$items.item"}],
                },
            },
            {
                "id": "bad",
                "type": "set",
                "data": {
                    "label": "logFailure",
                    "mappings": [{"key": "url", "value": "$items.item"}],
                },
            },
            {"id": "o", "type": "output", "data": {"label": "out", "message": "done"}},
        ]
        edges = [
            edge("in", "lp"),
            edge("lp", "h", "loop"),
            edge("h", "ok"),
            edge("h", "bad", "error"),
            edge("ok", "lp", None, "loop"),
            edge("bad", "lp", None, "loop"),
            edge("lp", "o", "done"),
        ]
        urls = ["https://example.test/a", "https://down.test/b", "https://example.test/c"]

        def respond(method: str, url: str, **_: object) -> httpx.Response:
            if "down.test" in str(url):
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client") as mock_get_client,
        ):
            mock_get_client.return_value.request.side_effect = respond
            result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
                workflow_id=uuid.uuid4(),
                initial_inputs={"headers": {}, "query": {}, "body": {"urls": urls}},
            )

        def ran(label: str) -> list[str]:
            return [
                row["output"]["url"]
                for row in result.node_results
                if row["node_label"] == label and row["status"] == "success"
            ]

        self.assertEqual(ran("saveResult"), [urls[0], urls[2]])
        self.assertEqual(ran("logFailure"), [urls[1]])
