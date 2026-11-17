"""Outlook and Microsoft 365 calendar events with Teams meetings, and bounded availability reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app.services.calendar_slots import (
    BusyEvent,
    availability_window,
    calendar_zone,
    format_intervals,
    free_intervals,
    label_busy_intervals,
    merge_intervals,
    parse_attendee_emails,
    parse_datetime,
)
from app.services.outlook_service import GRAPH_BASE, OutlookApiError, OutlookService

LABEL = "Outlook Calendar"
OUTLOOK_CALENDAR_SCOPES: tuple[str, ...] = ("offline_access", "User.Read", "Calendars.ReadWrite")
# Outlook's own scheduling assistant offers free and working-elsewhere time; anything else blocks.
BUSY_STATUSES = frozenset({"tentative", "busy", "oof", "unknown"})
TEAMS_PROVIDER = "teamsForBusiness"
PAGE_SIZE = 250
MAX_EVENT_PAGES = 40
MAX_CALENDARS = 500
_FRACTION = re.compile(r"(\.\d{6})\d+")

_STATUS_DETAIL = {
    401: "credential expired; reconnect it in Credentials",
    403: "calendar access denied; check sharing and the app's Calendars.ReadWrite permission",
    404: "calendar or event not found or not accessible",
    429: "Microsoft Graph rate limit reached; retry later",
}


def has_calendar_scope(scope: str) -> bool:
    """Whether a granted scope string includes Calendars.ReadWrite, short or full form."""
    return any(
        item.rsplit("/", 1)[-1].lower() == "calendars.readwrite"
        for item in str(scope or "").split()
    )


def graph_time(value: Any) -> datetime:
    """A Graph ``dateTimeTimeZone`` as an aware UTC datetime."""
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        raise HTTPException(502, f"{LABEL}: Microsoft Graph returned an invalid time")
    zone_name = str(value.get("timeZone") or "UTC").strip()
    try:
        result = datetime.fromisoformat(_FRACTION.sub(r"\1", value["dateTime"].strip()))
        if result.tzinfo is None:
            zone = (
                timezone.utc
                if zone_name.upper() in {"UTC", "ETC/UTC", "GMT"}
                else ZoneInfo(zone_name)
            )
            result = result.replace(tzinfo=zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(502, f"{LABEL}: Microsoft Graph returned an invalid time") from exc
    return result.astimezone(timezone.utc)


def graph_utc(moment: datetime) -> str:
    """A UTC wall-clock string for Graph ``dateTime`` fields paired with ``timeZone: UTC``."""
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


@dataclass(frozen=True)
class CalendarTarget:
    """Where a call goes: one of the account's calendars, or another person's schedule."""

    path: str = ""
    schedule: str = ""


class OutlookCalendarService(OutlookService):
    """Graph v1.0 calendar client for the signed-in account; refreshed tokens are saved."""

    scopes = OUTLOOK_CALENDAR_SCOPES
    label = LABEL
    status_detail = _STATUS_DETAIL
    # Times come back in UTC and event ids survive moves between calendars.
    prefer = 'IdType="ImmutableId", outlook.timezone="UTC"'

    def call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """One Graph request; failures become HTTP errors the node reports."""
        try:
            return self._json(method, url, **kwargs)
        except OutlookApiError as exc:
            status = exc.status_code if 400 <= exc.status_code < 600 else 502
            raise HTTPException(status, str(exc)) from exc

    def resolve_calendar(self, calendar: str, *, allow_schedule: bool) -> CalendarTarget:
        """``primary``, the account's own address, a calendar name or id, or another address."""
        value = (calendar or "").strip() or "primary"
        account = str(self._config.get("email_address") or "").strip().lower()
        if value.lower() == "primary" or (account and value.lower() == account):
            return CalendarTarget(path="calendar")
        if "@" in value:
            if not allow_schedule:
                raise HTTPException(
                    400,
                    f"{LABEL}: events can only be saved in your own calendars; "
                    "use primary or one of your calendar names",
                )
            return CalendarTarget(schedule=value)
        calendars = self._list_calendars()
        by_id = [item for item in calendars if item.get("id") == value]
        by_name = [
            item for item in calendars if str(item.get("name") or "").lower() == value.lower()
        ]
        if len(by_name) > 1 and not by_id:
            raise HTTPException(
                400, f"{LABEL}: more than one calendar has this name; use its calendar ID"
            )
        match = (by_id or by_name or [None])[0]
        if not match:
            raise HTTPException(
                404, f"{LABEL}: calendar not found; use primary, a calendar name or its ID"
            )
        return CalendarTarget(path=f"calendars/{quote(str(match['id']), safe='')}")

    def _list_calendars(self) -> list[dict[str, Any]]:
        """The account's calendars, ``id`` and ``name`` only."""
        calendars: list[dict[str, Any]] = []
        url: str | None = f"{GRAPH_BASE}/calendars"
        params: dict[str, Any] | None = {"$select": "id,name", "$top": "100"}
        while url and len(calendars) < MAX_CALENDARS:
            page = self.call("GET", url, params=params)
            calendars.extend(item for item in page.get("value") or [] if isinstance(item, dict))
            next_link = page.get("@odata.nextLink")
            url, params = (str(next_link) if next_link else None), None
        return calendars

    def _calendar_view(
        self, path: str, lower: datetime, upper: datetime, zone: ZoneInfo, *, details: bool
    ) -> list[BusyEvent]:
        """Every blocking occurrence in the window, recurring ones expanded, across all pages."""
        fields = "start,end,showAs,isCancelled,isAllDay"
        url: str | None = f"{GRAPH_BASE}/{path}/calendarView"
        params: dict[str, Any] | None = {
            "startDateTime": graph_utc(lower) + "Z",
            "endDateTime": graph_utc(upper) + "Z",
            "$select": f"{fields},subject,attendees" if details else fields,
            "$top": str(PAGE_SIZE),
        }
        events: list[BusyEvent] = []
        pages = 0
        while url:
            page = self.call("GET", url, params=params)
            items = page.get("value")
            if not isinstance(items, list):
                raise HTTPException(502, f"{LABEL}: invalid calendar response")
            for item in items:
                event = self._busy_event(item, zone, details=details)
                if event and event.end > lower and event.start < upper:
                    events.append(event)
            pages += 1
            next_link = page.get("@odata.nextLink")
            if next_link and pages >= MAX_EVENT_PAGES:
                raise HTTPException(
                    502, f"{LABEL}: too many events in this window; shorten the range"
                )
            url, params = (str(next_link) if next_link else None), None
        return events

    @staticmethod
    def _busy_event(item: Any, zone: ZoneInfo, *, details: bool) -> BusyEvent | None:
        if not isinstance(item, dict):
            raise HTTPException(502, f"{LABEL}: invalid calendar event")
        status = str(item.get("showAs") or "unknown")
        if item.get("isCancelled") is True or status not in BUSY_STATUSES:
            return None
        if item.get("isAllDay") is True:
            # All-day events float: the date holds wherever the reader is.
            try:
                left = parse_datetime(str(item["start"]["dateTime"])[:10], zone, LABEL)
                right = parse_datetime(str(item["end"]["dateTime"])[:10], zone, LABEL)
            except (KeyError, TypeError, HTTPException) as exc:
                raise HTTPException(502, f"{LABEL}: calendar event has invalid times") from exc
            left, right = left.astimezone(timezone.utc), right.astimezone(timezone.utc)
        else:
            left, right = graph_time(item.get("start")), graph_time(item.get("end"))
        if right <= left:
            return None
        if not details:
            return BusyEvent(left, right, None)
        subject = item.get("subject")
        attendees = [
            str(attendee["emailAddress"]["address"])
            for attendee in item.get("attendees") or []
            if isinstance(attendee, dict)
            and attendee.get("type") != "resource"
            and isinstance(attendee.get("emailAddress"), dict)
            and attendee["emailAddress"].get("address")
        ]
        return BusyEvent(left, right, subject if isinstance(subject, str) else None, attendees)

    def _schedule(self, address: str, lower: datetime, upper: datetime) -> list[BusyEvent]:
        """Another person's free/busy, as their organization lets this account see it."""
        result = self.call(
            "POST",
            f"{GRAPH_BASE}/calendar/getSchedule",
            json={
                "schedules": [address],
                "startTime": {"dateTime": graph_utc(lower), "timeZone": "UTC"},
                "endTime": {"dateTime": graph_utc(upper), "timeZone": "UTC"},
                "availabilityViewInterval": 30,
            },
        )
        entries = [item for item in result.get("value") or [] if isinstance(item, dict)]
        entry = next(
            (
                item
                for item in entries
                if str(item.get("scheduleId") or "").lower() == address.lower()
            ),
            entries[0] if len(entries) == 1 else None,
        )
        if not entry or entry.get("error") or not isinstance(entry.get("scheduleItems"), list):
            raise HTTPException(
                403,
                f"{LABEL}: calendar availability is not accessible; check sharing permissions",
            )
        events: list[BusyEvent] = []
        for item in entry["scheduleItems"]:
            if not isinstance(item, dict):
                raise HTTPException(502, f"{LABEL}: invalid availability response")
            if str(item.get("status") or "unknown") not in BUSY_STATUSES:
                continue
            left, right = graph_time(item.get("start")), graph_time(item.get("end"))
            if right <= left:
                continue
            subject = item.get("subject")
            title = subject if isinstance(subject, str) and not item.get("isPrivate") else None
            events.append(BusyEvent(left, right, title, None))
        return events

    def read_availability(
        self,
        calendar_id: str = "primary",
        start: str = "",
        end: str = "",
        time_zone: str = "UTC",
        *,
        include_busy_details: bool = False,
    ) -> dict[str, Any]:
        """Return free intervals between blocking events, failing closed on inaccessible data."""
        start_at, end_at = availability_window(start, end, time_zone, LABEL)
        zone = calendar_zone(time_zone, LABEL)
        lower, upper = start_at.astimezone(timezone.utc), end_at.astimezone(timezone.utc)
        target = self.resolve_calendar(calendar_id, allow_schedule=True)
        if target.schedule:
            events = self._schedule(target.schedule, lower, upper)
        else:
            events = self._calendar_view(
                target.path, lower, upper, zone, details=include_busy_details
            )
        clipped = [
            BusyEvent(max(event.start, lower), min(event.end, upper), event.title, event.attendees)
            for event in events
            if event.end > lower and event.start < upper
        ]
        merged = merge_intervals((event.start, event.end) for event in clipped)
        free = free_intervals(merged, lower, upper)
        busy_slots: list[dict[str, Any]] = list(format_intervals(merged, zone))
        if include_busy_details and merged:
            busy_slots = label_busy_intervals(merged, clipped, zone)
        return {
            "status": "success",
            "operation": "read",
            "calendar_id": (calendar_id or "").strip() or "primary",
            "time_zone": time_zone,
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "available_slots": format_intervals(free, zone),
            "busy_slots": busy_slots,
            "count": len(free),
        }

    def save_event(
        self,
        operation: str,
        calendar_id: str,
        event_id: str,
        *,
        title: str = "",
        description: str = "",
        start: str = "",
        end: str = "",
        time_zone: str = "UTC",
        attendees: str | list[Any] = "",
        location: str = "",
        teams_meeting: bool = True,
    ) -> dict[str, Any]:
        """Create an invitation, with a Teams link when the account offers one, or patch one."""
        if operation not in {"create", "update"}:
            raise HTTPException(400, f"{LABEL}: unsupported save operation")
        if operation == "create" and not (title.strip() and start.strip() and end.strip()):
            raise HTTPException(400, f"{LABEL}: create requires title, start and end")
        if operation == "update" and not event_id:
            raise HTTPException(400, f"{LABEL}: update requires an event ID")
        zone = calendar_zone(time_zone, LABEL)
        body: dict[str, Any] = {}
        if title.strip():
            body["subject"] = title
        if description.strip():
            body["body"] = {"contentType": "text", "content": description}
        if location.strip():
            body["location"] = {"displayName": location}
        if bool(start.strip()) != bool(end.strip()):
            raise HTTPException(400, f"{LABEL}: supply both start and end when rescheduling")
        if start.strip() and end.strip():
            start_at = parse_datetime(start, zone, LABEL)
            end_at = parse_datetime(end, zone, LABEL)
            if end_at.astimezone(timezone.utc) <= start_at.astimezone(timezone.utc):
                raise HTTPException(400, f"{LABEL}: event end must be after start")
            body["start"] = {"dateTime": graph_utc(start_at), "timeZone": "UTC"}
            body["end"] = {"dateTime": graph_utc(end_at), "timeZone": "UTC"}
        if attendees or isinstance(attendees, list):
            body["attendees"] = [
                {"emailAddress": {"address": email}, "type": "required"}
                for email in parse_attendee_emails(attendees, LABEL)
            ]
        teams_unavailable = False
        if operation == "create":
            target = self.resolve_calendar(calendar_id, allow_schedule=False)
            if teams_meeting:
                calendar = self.call(
                    "GET",
                    f"{GRAPH_BASE}/{target.path}",
                    params={"$select": "allowedOnlineMeetingProviders"},
                )
                if TEAMS_PROVIDER in (calendar.get("allowedOnlineMeetingProviders") or []):
                    body["isOnlineMeeting"] = True
                    body["onlineMeetingProvider"] = TEAMS_PROVIDER
                else:
                    teams_unavailable = True
            event = self.call("POST", f"{GRAPH_BASE}/{target.path}/events", json=body)
        else:
            if not body:
                raise HTTPException(400, f"{LABEL}: provide at least one field to update")
            event = self.call("PATCH", f"{GRAPH_BASE}/events/{quote(event_id, safe='')}", json=body)
        online = event.get("onlineMeeting")
        teams_url = str(online.get("joinUrl") or "") if isinstance(online, dict) else ""
        if teams_url:
            teams_status = "ready"
        elif event.get("isOnlineMeeting") is True:
            teams_status = "pending"
        else:
            teams_status = "unavailable" if teams_unavailable else "off"
        result: dict[str, Any] = {
            "status": "success",
            "operation": operation,
            "event_id": str(event.get("id") or ""),
            "teams_url": teams_url,
            "teams_status": teams_status,
            "web_link": str(event.get("webLink") or ""),
            "event": event,
        }
        if operation == "create":
            result["calendar_id"] = (calendar_id or "").strip() or "primary"
        return result

    def delete_event(self, event_id: str) -> dict[str, Any]:
        """Delete an event; Outlook sends cancellations when the account organized it."""
        if not event_id:
            raise HTTPException(400, f"{LABEL}: delete requires an event ID")
        self.call("DELETE", f"{GRAPH_BASE}/events/{quote(event_id, safe='')}")
        return {"status": "success", "operation": "delete", "event_id": event_id, "deleted": True}
