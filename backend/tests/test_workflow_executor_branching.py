import unittest
import uuid

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


if __name__ == "__main__":
    unittest.main()
