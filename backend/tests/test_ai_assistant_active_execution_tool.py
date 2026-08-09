import json
import unittest

from app.api import ai_assistant
from app.services import mcp_chat_service


class TestActiveExecutionToolRegistered(unittest.TestCase):
    def test_tool_present_without_arguments(self):
        tool = next(
            item
            for item in ai_assistant.DASHBOARD_CHAT_TOOLS
            if item["function"]["name"] == "get_active_executions"
        )
        self.assertEqual(tool["function"]["parameters"], {"type": "object", "properties": {}})

    def test_prompt_routes_running_questions_to_the_tool(self):
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("get_active_executions", prompt)
        self.assertIn("running_for", prompt)
        self.assertIn("current_nodes", prompt)

    def test_mcp_chat_tool_advertises_the_capability(self):
        self.assertIn("running right now", mcp_chat_service.MCP_CHAT_TOOL_DESCRIPTION)


class TestActiveExecutionToolSummary(unittest.TestCase):
    def _summary(self, payload: dict) -> str:
        return ai_assistant._summarize_tool_result("get_active_executions", json.dumps(payload))

    def test_no_active_runs(self):
        self.assertEqual(
            self._summary({"count": 0, "running_count": 0, "pending_count": 0, "executions": []}),
            "No workflows are running right now",
        )

    def test_counts_running_and_pending(self):
        self.assertEqual(
            self._summary(
                {"count": 3, "running_count": 2, "pending_count": 1, "executions": []},
            ),
            "3 active execution(s), 1 awaiting review",
        )

    def test_running_only_omits_review_suffix(self):
        self.assertEqual(
            self._summary({"count": 2, "running_count": 2, "pending_count": 0, "executions": []}),
            "2 active execution(s)",
        )

    def test_error_is_surfaced(self):
        self.assertEqual(
            self._summary({"error": "database is down"}),
            "Error: database is down",
        )

    def test_error_payload_marks_tool_call_failed(self):
        status = ai_assistant._chat_tool_lifecycle_status(
            "get_active_executions", json.dumps({"error": "database is down"})
        )
        self.assertEqual(status, "error")

    def test_success_payload_marks_tool_call_success(self):
        status = ai_assistant._chat_tool_lifecycle_status(
            "get_active_executions",
            json.dumps({"count": 1, "running_count": 1, "pending_count": 0, "executions": []}),
        )
        self.assertEqual(status, "success")


if __name__ == "__main__":
    unittest.main()
