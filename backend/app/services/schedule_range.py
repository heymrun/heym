"""Resolve calendar day / week / month bounds in a timezone (matches Scheduled tab semantics)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Literal

ViewWindow = Literal["day", "week", "month"]

_MAX_RANGE_DAYS = 62


def _parse_iso_datetime(value: str) -> datetime:
    cleaned = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def parse_iso_range(
    start_iso: str, end_iso: str, max_days: int = _MAX_RANGE_DAYS
) -> tuple[datetime, datetime]:
    """Parse start/end ISO datetimes and enforce ordering and max span (same rules as GET /api/schedules)."""
    start = _parse_iso_datetime(start_iso)
    end = _parse_iso_datetime(end_iso)
    if end <= start:
        raise ValueError("end must be after start")
    if (end - start).days > max_days:
        raise ValueError(f"Date range must not exceed {max_days} days")
    return start, end


def resolve_schedule_tool_range(
    view_window: str | None,
    reference_date_str: str | None,
    start_iso: str | None,
    end_iso: str | None,
    tz: tzinfo,
) -> tuple[datetime, datetime]:
    """Compute [start, end] for dashboard chat get_schedule_events tool."""
    if start_iso and end_iso and str(start_iso).strip() and str(end_iso).strip():
        return parse_iso_range(str(start_iso), str(end_iso))
    if not view_window or view_window not in ("day", "week", "month"):
        raise ValueError(
            "Provide view_window (day, week, or month) with optional reference_date, "
            "or both start_iso and end_iso (ISO-8601)",
        )
    ref = datetime.now(tz).date()
    if reference_date_str and str(reference_date_str).strip():
        ref = date.fromisoformat(str(reference_date_str).strip())
    return bounds_for_view_window(view_window, ref, tz)


def calendar_day_bounds(reference: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """Start of day through end of day in `tz`."""
    start = datetime.combine(reference, time.min, tzinfo=tz)
    end = datetime.combine(reference, time(23, 59, 59, 999999), tzinfo=tz)
    return start, end


def calendar_week_bounds(reference: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """Monday 00:00 through Sunday 23:59:59.999999 in `tz` (same as dashboard Scheduled week view)."""
    monday = reference - timedelta(days=reference.weekday())
    sunday = monday + timedelta(days=6)
    start, _ = calendar_day_bounds(monday, tz)
    _, end = calendar_day_bounds(sunday, tz)
    return start, end


def calendar_month_bounds(reference: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """First day 00:00 through last day 23:59:59.999999 of the month containing `reference`."""
    first = reference.replace(day=1)
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1, day=1)
    else:
        next_month = first.replace(month=first.month + 1, day=1)
    last_day = next_month - timedelta(days=1)
    start, _ = calendar_day_bounds(first, tz)
    _, end = calendar_day_bounds(last_day, tz)
    return start, end


def bounds_for_view_window(
    view: ViewWindow, reference: date, tz: tzinfo
) -> tuple[datetime, datetime]:
    if view == "day":
        return calendar_day_bounds(reference, tz)
    if view == "week":
        return calendar_week_bounds(reference, tz)
    return calendar_month_bounds(reference, tz)
