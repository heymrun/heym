"""Chat's time_range enums offer the hour windows, and every value they offer is honoured."""

import unittest
from datetime import datetime, timezone

from app.api import ai_assistant
from app.services.analytics_metrics import time_range_start
from app.services.workflow_run_history_tool import _TIME_RANGE_HOURS

HOUR_RANGES = ["1h", "3h", "6h"]
RANGE_TOOLS = [
    "get_analytics_stats",
    "get_analytics_breakdown",
    "get_recent_executions",
    "get_workflow_run_history",
]


def _time_range_enum(tool_name: str) -> list[str]:
    for tool in ai_assistant.DASHBOARD_CHAT_TOOLS:
        function = tool["function"]
        if function["name"] == tool_name:
            return function["parameters"]["properties"]["time_range"]["enum"]
    raise AssertionError(f"{tool_name} is not a dashboard chat tool")


class ChatTimeRangeEnumTests(unittest.TestCase):
    def test_range_tools_offer_the_hour_windows(self) -> None:
        for tool_name in RANGE_TOOLS:
            with self.subTest(tool=tool_name):
                offered = _time_range_enum(tool_name)
                for hour_range in HOUR_RANGES:
                    self.assertIn(hour_range, offered)
                self.assertEqual(offered, ai_assistant.CHAT_TIME_RANGES)

    def test_every_offered_range_is_a_window_analytics_knows(self) -> None:
        now = datetime(2026, 10, 28, 15, 20, tzinfo=timezone.utc)
        seven_days = time_range_start("7d", now=now)
        for time_range in ai_assistant.CHAT_TIME_RANGES:
            with self.subTest(time_range=time_range):
                if time_range != "7d":
                    # An unknown name silently becomes 7d, which is the bug this guards.
                    self.assertNotEqual(time_range_start(time_range, now=now), seven_days)

    def test_hour_windows_start_on_the_hour(self) -> None:
        now = datetime(2026, 10, 28, 15, 20, tzinfo=timezone.utc)
        self.assertEqual(
            time_range_start("1h", now=now), datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(
            time_range_start("3h", now=now), datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(
            time_range_start("6h", now=now), datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
        )

    def test_recent_executions_and_run_history_honour_every_offered_range(self) -> None:
        for time_range in ai_assistant.CHAT_TIME_RANGES:
            with self.subTest(time_range=time_range):
                self.assertIn(time_range, ai_assistant.RECENT_EXECUTIONS_SINCE_HOURS)
                self.assertIn(time_range, _TIME_RANGE_HOURS)

    def test_hour_windows_look_back_that_many_hours(self) -> None:
        for time_range, hours in (("1h", 1), ("3h", 3), ("6h", 6)):
            with self.subTest(time_range=time_range):
                self.assertEqual(ai_assistant.RECENT_EXECUTIONS_SINCE_HOURS[time_range], hours)
                self.assertEqual(_TIME_RANGE_HOURS[time_range], hours)

    def test_system_prompt_names_the_hour_windows(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("1h, 3h or 6h for the last hours", prompt)
        self.assertIn("top of the hour", prompt)


if __name__ == "__main__":
    unittest.main()
