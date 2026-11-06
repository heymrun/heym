"""Opt-in event titles layered over authoritative Calendar free/busy intervals."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import HTTPException


@dataclass(frozen=True)
class BusyEvent:
    """An event occurrence with only the data needed to label a busy interval."""

    start: datetime
    end: datetime
    title: str | None


def read_busy_events(
    request: Callable[..., dict[str, Any]],
    calendar_id: str,
    lower: datetime,
    upper: datetime,
) -> list[BusyEvent]:
    """Read every occurrence in the window without fetching descriptions or guest lists."""
    from app.services.google_meet_service import calendar_zone, parse_datetime

    events: list[BusyEvent] = []
    page_token = ""
    seen_tokens: set[str] = set()
    while True:
        params: dict[str, Any] = {
            "timeMin": lower.isoformat(),
            "timeMax": upper.isoformat(),
            "singleEvents": True,
            "showDeleted": False,
            "maxResults": 2500,
            "fields": "nextPageToken,timeZone,items(summary,start,end,status,transparency)",
        }
        if page_token:
            params["pageToken"] = page_token
        page = request("GET", f"calendars/{quote(calendar_id, safe='')}/events", params=params)
        items = page.get("items", [])
        if not isinstance(items, list):
            raise HTTPException(502, "Google Meet: invalid Calendar events response")
        # No timeZone query override: all-day dates belong to the calendar's own zone.
        zone = calendar_zone(page.get("timeZone") or "UTC")
        for event in items:
            if not isinstance(event, dict):
                raise HTTPException(502, "Google Meet: invalid Calendar event")
            if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
                continue
            try:
                start = event["start"]
                end = event["end"]
                left = parse_datetime(
                    start.get("dateTime") or start["date"],
                    calendar_zone(start.get("timeZone") or zone.key),
                )
                right = parse_datetime(
                    end.get("dateTime") or end["date"],
                    calendar_zone(end.get("timeZone") or zone.key),
                )
            except (KeyError, TypeError, AttributeError) as exc:
                raise HTTPException(502, "Google Meet: Calendar event has invalid times") from exc
            left, right = left.astimezone(timezone.utc), right.astimezone(timezone.utc)
            if right <= left:
                raise HTTPException(502, "Google Meet: Calendar event has an invalid time range")
            if left < upper and right > lower:
                title = event.get("summary")
                events.append(
                    BusyEvent(
                        max(left, lower),
                        min(right, upper),
                        title if isinstance(title, str) else None,
                    )
                )
        page_token = page.get("nextPageToken", "")
        if not page_token:
            return events
        if not isinstance(page_token, str) or page_token in seen_tokens:
            raise HTTPException(502, "Google Meet: invalid Calendar events pagination")
        seen_tokens.add(page_token)


def label_busy_intervals(
    busy: list[tuple[datetime, datetime]], events: list[BusyEvent], zone: ZoneInfo
) -> list[dict[str, str | None]]:
    """Keep each event's title and retain any unlabelled busy time with a null title."""
    slots: list[BusyEvent] = []

    def append(left: datetime, right: datetime, title: str | None) -> None:
        slots.append(BusyEvent(left, right, title))

    ordered_events = sorted(events, key=lambda event: (event.start, event.end))
    for left, right in busy:
        cursor = left
        for event in ordered_events:
            if event.end <= left or event.start >= right:
                continue
            start, end = max(left, event.start), min(right, event.end)
            if cursor < start:
                append(cursor, start, None)
            append(start, end, event.title)
            cursor = max(cursor, end)
        if cursor < right:
            append(cursor, right, None)
    return [
        {
            "start": slot.start.astimezone(zone).isoformat(),
            "end": slot.end.astimezone(zone).isoformat(),
            "title": slot.title,
        }
        for slot in sorted(slots, key=lambda slot: (slot.start, slot.end))
    ]
