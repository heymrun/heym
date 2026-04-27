import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.schedule_range import (
    bounds_for_view_window,
    calendar_week_bounds,
    parse_iso_range,
    resolve_schedule_tool_range,
)


class TestScheduleRange(unittest.TestCase):
    def test_parse_iso_range_valid(self) -> None:
        start = "2026-04-20T00:00:00+00:00"
        end = "2026-04-21T00:00:00+00:00"
        a, b = parse_iso_range(start, end)
        self.assertLess(a, b)
        self.assertEqual((b - a).days, 1)

    def test_parse_iso_range_rejects_order(self) -> None:
        with self.assertRaises(ValueError):
            parse_iso_range("2026-04-21T00:00:00Z", "2026-04-20T00:00:00Z")

    def test_parse_iso_range_rejects_span(self) -> None:
        with self.assertRaises(ValueError):
            parse_iso_range(
                "2026-01-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
            )

    def test_week_bounds_monday_sunday(self) -> None:
        tz = ZoneInfo("UTC")
        # 2026-04-20 is Monday
        ref = date(2026, 4, 22)  # Wednesday
        start, end = calendar_week_bounds(ref, tz)
        self.assertEqual(start.weekday(), 0)
        self.assertEqual(end.weekday(), 6)
        self.assertEqual(start.date(), date(2026, 4, 20))
        self.assertEqual(end.date(), date(2026, 4, 26))

    def test_resolve_custom_iso_overrides_view(self) -> None:
        tz = ZoneInfo("UTC")
        a, b = resolve_schedule_tool_range(
            "week",
            None,
            "2026-04-20T00:00:00+00:00",
            "2026-04-21T00:00:00+00:00",
            tz,
        )
        self.assertEqual(a, datetime(2026, 4, 20, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(b, datetime(2026, 4, 21, 0, 0, 0, tzinfo=timezone.utc))

    def test_resolve_day_view(self) -> None:
        tz = ZoneInfo("UTC")
        a, b = resolve_schedule_tool_range(
            "day",
            "2026-04-20",
            None,
            None,
            tz,
        )
        self.assertEqual(a.date(), date(2026, 4, 20))
        self.assertEqual(b.date(), date(2026, 4, 20))

    def test_bounds_for_view_window_month(self) -> None:
        tz = ZoneInfo("UTC")
        start, end = bounds_for_view_window("month", date(2026, 4, 15), tz)
        self.assertEqual(start.day, 1)
        self.assertEqual(start.month, 4)
        self.assertEqual(end.month, 4)
        self.assertEqual(end.day, 30)


if __name__ == "__main__":
    unittest.main()
