"""Calendar time handling shared by the Google Meet and Outlook Calendar nodes.

Every helper takes the node's ``label`` so its errors name the node the user configured.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

MAX_AVAILABILITY_DAYS = 60
_EMAIL_PATTERN = re.compile(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+")
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class BusyEvent:
    """An event occurrence with only the data needed to label a busy interval."""

    start: datetime
    end: datetime
    title: str | None
    attendees: list[str] | None = None


def calendar_zone(name: str, label: str) -> ZoneInfo:
    """Validate an IANA time zone before interpreting local dates."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(400, f"{label}: use a valid IANA time zone") from exc


def parse_datetime(value: str, zone: ZoneInfo, label: str) -> datetime:
    """Interpret ISO dates/datetimes in the selected zone and retain explicit offsets."""
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, f"{label}: dates must use ISO 8601 format")
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, f"{label}: dates must use ISO 8601 format") from exc
    if result.tzinfo is not None:
        return result.astimezone(zone)
    if _DATE_ONLY.fullmatch(value.strip()):
        # A date is the whole day, from its first instant. Where daylight saving starts at
        # midnight (Africa/Cairo, America/Santiago) there is no 00:00 and the day starts at
        # 01:00; all-day events arrive as dates and must not fail the read there.
        return result.replace(tzinfo=zone).astimezone(timezone.utc).astimezone(zone)
    result = result.replace(tzinfo=zone)
    if result.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != result.replace(
        tzinfo=None
    ):
        raise HTTPException(400, f"{label}: this local time does not exist; use an offset")
    if result.utcoffset() != result.replace(fold=1).utcoffset():
        raise HTTPException(400, f"{label}: ambiguous local time; include a UTC offset")
    return result


def availability_window(
    start: str, end: str, time_zone: str, label: str, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Default to now through next month's first midnight, with a 60-day maximum."""
    zone = calendar_zone(time_zone, label)
    start_at = parse_datetime(start, zone, label) if start.strip() else (now or datetime.now(zone))
    start_at = start_at.astimezone(zone)
    end_at = (
        parse_datetime(end, zone, label)
        if end.strip()
        else start_at.replace(
            year=start_at.year + (start_at.month == 12),
            month=start_at.month % 12 + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    )
    # Calendar days keep a 60-day query valid across a daylight-saving transition.
    if end_at <= start_at or end_at > start_at + timedelta(days=MAX_AVAILABILITY_DAYS):
        raise HTTPException(400, f"{label}: end must follow start by at most 60 days")
    return start_at, end_at


def parse_attendee_emails(value: str | list[Any], label: str) -> list[str]:
    """Accept email lists as JSON arrays or comma/semicolon/newline separated text."""
    if isinstance(value, str):
        if value.strip().startswith("["):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise HTTPException(400, f"{label}: invalid attendee JSON array") from exc
        else:
            value = [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]
    if not isinstance(value, list):
        raise HTTPException(400, f"{label}: attendees must be a list of email addresses")
    emails: list[str] = []
    seen: set[str] = set()
    for item in value:
        email = item.get("email", "") if isinstance(item, dict) else item
        if not isinstance(email, str) or not _EMAIL_PATTERN.fullmatch(email.strip()):
            raise HTTPException(400, f"{label}: each attendee must have a valid email address")
        email = email.strip()
        if email.lower() not in seen:
            emails.append(email)
            seen.add(email.lower())
    return emails


def merge_intervals(busy: Iterable[Interval]) -> list[Interval]:
    """Merge overlapping and adjacent UTC intervals."""
    merged: list[Interval] = []
    for left, right in sorted(busy):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged


def free_intervals(merged: list[Interval], lower: datetime, upper: datetime) -> list[Interval]:
    """The gaps between merged busy intervals inside ``[lower, upper)``."""
    free: list[Interval] = []
    cursor = lower
    for left, right in merged:
        if cursor < left:
            free.append((cursor, left))
        cursor = right
    if cursor < upper:
        free.append((cursor, upper))
    return free


def format_intervals(values: list[Interval], zone: ZoneInfo) -> list[dict[str, str]]:
    """Intervals as ``{start, end}`` ISO strings in the selected zone."""
    return [
        {"start": a.astimezone(zone).isoformat(), "end": b.astimezone(zone).isoformat()}
        for a, b in values
    ]


def label_busy_intervals(
    busy: list[Interval], events: list[BusyEvent], zone: ZoneInfo
) -> list[dict[str, Any]]:
    """Keep each event's details and retain any unlabelled busy time with null details."""
    slots: list[BusyEvent] = []
    ordered_events = sorted(events, key=lambda event: (event.start, event.end))
    for left, right in busy:
        cursor = left
        for event in ordered_events:
            if event.end <= left or event.start >= right:
                continue
            start, end = max(left, event.start), min(right, event.end)
            if cursor < start:
                slots.append(BusyEvent(cursor, start, None, None))
            slots.append(BusyEvent(start, end, event.title, event.attendees))
            cursor = max(cursor, end)
        if cursor < right:
            slots.append(BusyEvent(cursor, right, None, None))
    return [
        {
            "start": slot.start.astimezone(zone).isoformat(),
            "end": slot.end.astimezone(zone).isoformat(),
            "title": slot.title,
            "attendees": slot.attendees,
        }
        for slot in sorted(slots, key=lambda slot: (slot.start, slot.end))
    ]
