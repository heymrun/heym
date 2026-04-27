"""Unit tests for dashboard chat tool result summaries (run history step labels)."""

import json
import unittest

from app.api.ai_assistant import _summarize_tool_result


class TestSummarizeScheduleEventsTool(unittest.TestCase):
    def test_counts_occurrences(self) -> None:
        payload = json.dumps({"total": 5, "events": []})
        out = _summarize_tool_result("get_schedule_events", payload)
        self.assertEqual(out, "5 scheduled occurrence(s)")

    def test_zero_occurrences(self) -> None:
        payload = json.dumps({"total": 0, "events": []})
        out = _summarize_tool_result("get_schedule_events", payload)
        self.assertEqual(out, "0 scheduled occurrence(s)")

    def test_error_message(self) -> None:
        payload = json.dumps({"error": "end must be after start"})
        out = _summarize_tool_result("get_schedule_events", payload)
        self.assertIn("Error:", out)
        self.assertIn("end must be after start", out)


if __name__ == "__main__":
    unittest.main()
