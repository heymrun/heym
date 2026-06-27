import unittest
import uuid
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

        with patch("app.services.workflow_executor.get_http_client") as mock_get_client:
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


if __name__ == "__main__":
    unittest.main()
