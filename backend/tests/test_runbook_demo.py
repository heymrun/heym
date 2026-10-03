import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor

RUNBOOK_INPUT_TEXT = "Heym runs and governs AI agents in production"
RUNBOOK_EXPECTED_LOG = "HEYM RUNS AND GOVERNS AI AGENTS IN PRODUCTION"


def _make_runbook_workflow() -> tuple[list[dict], list[dict], dict]:
    """The exact graph the Runbook demo builds: textInput -> wait -> consoleLog."""
    nodes = [
        {
            "id": "in1",
            "type": "textInput",
            "data": {"label": "start", "value": "", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "wait1",
            # duration 0 keeps the test instant; the live demo uses 2000ms.
            "type": "wait",
            "data": {"label": "wait", "duration": 0},
        },
        {
            "id": "log1",
            "type": "consoleLog",
            "data": {"label": "consoleLog", "logMessage": "$input.text.upper()"},
        },
    ]
    edges = [
        {"id": "e1", "source": "in1", "target": "wait1"},
        {"id": "e2", "source": "wait1", "target": "log1"},
    ]
    initial_inputs = {"headers": {}, "query": {}, "body": {"text": RUNBOOK_INPUT_TEXT}}
    return nodes, edges, initial_inputs


class RunbookDemoExecutionTest(unittest.TestCase):
    def test_runbook_graph_runs_and_logs_uppercase(self) -> None:
        nodes, edges, initial_inputs = _make_runbook_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        with self.assertLogs("heym.workflow", level="INFO") as captured:
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=initial_inputs)

        self.assertEqual(result.status, "success")

        results = {row["node_label"]: row for row in result.node_results}
        self.assertEqual(results["start"]["status"], "success")
        self.assertEqual(results["wait"]["status"], "success")
        self.assertEqual(results["consoleLog"]["status"], "success")

        # The consoleLog node logs the resolved $input.text.upper() to the heym.workflow logger.
        joined = "\n".join(captured.output)
        self.assertIn(RUNBOOK_EXPECTED_LOG, joined)
        self.assertEqual(results["consoleLog"]["output"]["logMessage"], RUNBOOK_EXPECTED_LOG)


if __name__ == "__main__":
    unittest.main()
