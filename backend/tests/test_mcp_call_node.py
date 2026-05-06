"""Unit tests for mcpCall node executor logic."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.workflow_executor import WorkflowExecutor

CONNECTION = {
    "id": "conn1",
    "transport": "sse",
    "url": "http://localhost:3000/sse",
    "timeoutSeconds": 30,
}


def _make_executor(node_data: dict) -> WorkflowExecutor:
    """Build a minimal WorkflowExecutor with a single mcpCall node."""
    node_id = "node_mcp1"
    nodes = [{"id": node_id, "type": "mcpCall", "data": node_data}]
    return WorkflowExecutor(nodes=nodes, edges=[])


class MCPCallNodeTests(unittest.TestCase):
    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_basic_tool_call(self, mock_exec: MagicMock) -> None:
        """execute_mcp_tool is called with correct args; result wrapped in {'result': ...}."""
        mock_exec.return_value = {"key": "value"}
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "search",
                "toolArguments": {"query": "hello"},
                "timeoutSeconds": 30,
            }
        )
        result = executor.execute_node("node_mcp1", {})
        mock_exec.assert_called_once_with(CONNECTION, "search", {"query": "hello"}, 30.0)
        self.assertEqual(result.output["result"], {"key": "value"})

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_json_result_already_unwrapped(self, mock_exec: MagicMock) -> None:
        """execute_mcp_tool returns a dict (already unwrapped); node wraps it in result key."""
        mock_exec.return_value = {"answer": 42}
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "calculate",
                "toolArguments": {},
                "timeoutSeconds": 30,
            }
        )
        result = executor.execute_node("node_mcp1", {})
        self.assertIsInstance(result.output["result"], dict)
        self.assertEqual(result.output["result"]["answer"], 42)

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_string_result_passthrough(self, mock_exec: MagicMock) -> None:
        """When tool returns plain text, result.output['result'] is that string."""
        mock_exec.return_value = "plain text response"
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "greet",
                "toolArguments": {},
                "timeoutSeconds": 30,
            }
        )
        result = executor.execute_node("node_mcp1", {})
        self.assertEqual(result.output["result"], "plain text response")

    def test_missing_tool_raises(self) -> None:
        """selectedTool='' causes the node to fail with a ValueError."""
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "",
                "toolArguments": {},
                "timeoutSeconds": 30,
            }
        )
        result = executor.execute_node("node_mcp1", {})
        self.assertEqual(result.status, "error")
        self.assertIn("requires a tool", str(result.error))

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_dsl_arguments_resolved(self, mock_exec: MagicMock) -> None:
        """DSL expression in toolArguments is resolved against inputs before calling the tool."""
        mock_exec.return_value = "ok"
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "search",
                "toolArguments": {"query": "$userInput.body.text"},
                "timeoutSeconds": 30,
            }
        )
        inputs = {"userInput": {"body": {"text": "hello world"}}}
        executor.node_outputs["node_mcp1"] = {}
        executor.label_to_output["userInput"] = {"body": {"text": "hello world"}}
        executor.execute_node("node_mcp1", inputs)
        resolved_args = mock_exec.call_args[0][2]
        self.assertEqual(resolved_args["query"], "hello world")

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_timeout_passed(self, mock_exec: MagicMock) -> None:
        """timeoutSeconds from node_data is passed to execute_mcp_tool as float."""
        mock_exec.return_value = None
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "ping",
                "toolArguments": {},
                "timeoutSeconds": 60,
            }
        )
        executor.execute_node("node_mcp1", {})
        passed_timeout = mock_exec.call_args[0][3]
        self.assertEqual(passed_timeout, 60.0)

    @patch("app.services.mcp_tool_executor.execute_mcp_tool")
    def test_default_timeout_when_missing(self, mock_exec: MagicMock) -> None:
        """When timeoutSeconds is absent, defaults to 30.0."""
        mock_exec.return_value = None
        executor = _make_executor(
            {
                "label": "mcpCall",
                "connection": CONNECTION,
                "selectedTool": "ping",
                "toolArguments": {},
            }
        )
        executor.execute_node("node_mcp1", {})
        passed_timeout = mock_exec.call_args[0][3]
        self.assertEqual(passed_timeout, 30.0)
