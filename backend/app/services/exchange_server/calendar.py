"""Outlook Calendar on an Exchange Server, over EWS.

Same operations and output as the Graph calendar (outlook_calendar_service.py): free time
in a window, a colleague's free/busy, and events created, updated or deleted with
invitations and cancellations sent by Exchange. Exchange Server has no Teams meetings.
"""

from __future__ import annotations

import warnings
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from exchangelib import CalendarItem, EWSDateTime
from exchangelib.items import SEND_TO_ALL_AND_SAVE_COPY, SEND_TO_NONE
from exchangelib.properties import ItemId
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
from app.services.exchange_server.connection import (
    ews_account,
    ews_errors,
    ews_settings,
    raise_failed,
    to_utc,
)
from app.services.outlook_service import OutlookApiError

LABEL = "Outlook Calendar"
# The view leaves the time zone fields out; exchangelib warns about the empty value each read.
warnings.filterwarnings(
    "ignore",
    message=r"Cannot convert value '' on field '_(start|end)_timezone'",
    category=UserWarning,
)
# Outlook's scheduling assistant offers free and working-elsewhere time; anything else blocks.
BUSY_STATUSES = frozenset({"Tentative", "Busy", "OOF", "NoData"})
MAX_EVENTS = 10_000
_VIEW_FIELDS = (
    "start",
    "end",
    "legacy_free_busy_status",
    "is_cancelled",
    "is_all_day",
    "subject",
    "required_attendees",
    "optional_attendees",
)


def _ews_time(moment: datetime) -> EWSDateTime:
    return EWSDateTime.from_datetime(moment.astimezone(timezone.utc))


def _utc(value: Any, zone: ZoneInfo) -> datetime:
    """An EWS start or end as aware UTC; a bare date (all-day) is midnight in ``zone``."""
    if isinstance(value, datetime):
        return to_utc(value)
    if isinstance(value, date):
        return parse_datetime(value.isoformat(), zone, LABEL).astimezone(timezone.utc)
    raise HTTPException(502, f"{LABEL}: Exchange returned an invalid time")


def _attendee_emails(item: Any) -> list[str]:
    attendees = [*(item.required_attendees or []), *(item.optional_attendees or [])]
    return [
        str(attendee.mailbox.email_address)
        for attendee in attendees
        if getattr(attendee, "mailbox", None) and attendee.mailbox.email_address
    ]


def _all_day_utc(value: Any, zone: ZoneInfo) -> datetime:
    """All-day events float: the date holds wherever the reader is."""
    day = value.date() if isinstance(value, datetime) else value
    return parse_datetime(day.isoformat(), zone, LABEL).astimezone(timezone.utc)


def busy_event(item: Any, zone: ZoneInfo, *, details: bool) -> BusyEvent | None:
    """One calendar-view occurrence as a blocking interval, or None when it does not block."""
    status = str(item.legacy_free_busy_status or "NoData")
    if item.is_cancelled is True or status not in BUSY_STATUSES:
        return None
    if item.is_all_day is True:
        left, right = _all_day_utc(item.start, zone), _all_day_utc(item.end, zone)
    else:
        left, right = _utc(item.start, zone), _utc(item.end, zone)
    if right <= left:
        return None
    if not details:
        return BusyEvent(left, right, None)
    subject = item.subject if isinstance(item.subject, str) else None
    return BusyEvent(left, right, subject, _attendee_emails(item))


def event_output(item: Any) -> dict[str, Any]:
    """The saved event, in the keys a Graph event would carry where they exist."""

    def moment(value: Any) -> str:
        return value.isoformat() if isinstance(value, (date, datetime)) else ""

    return {
        "id": str(item.id or ""),
        "subject": str(item.subject or ""),
        "start": moment(item.start),
        "end": moment(item.end),
        "isAllDay": item.is_all_day is True,
        "location": str(item.location or ""),
        "attendees": _attendee_emails(item),
        "webLink": str(item.web_client_read_form_query_string or ""),
    }


class ExchangeCalendarService:
    """The Exchange Server calendars of the credential's own mailbox."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._account: Any = None

    @property
    def account(self) -> Any:
        if self._account is None:
            self._account = self.call(lambda: ews_account(self._config))
        return self._account

    @staticmethod
    def call(action: Any) -> Any:
        """Run one EWS call; failures become HTTP errors the node reports."""
        try:
            with ews_errors(LABEL):
                return action()
        except OutlookApiError as exc:
            status = exc.status_code if 400 <= exc.status_code < 600 else 502
            raise HTTPException(status, str(exc)) from exc

    def _calendars(self) -> list[Any]:
        account = self.account
        found = [account.calendar]

        def collect() -> None:
            for folder in account.msg_folder_root.walk():
                if str(folder.folder_class or "").startswith("IPF.Appointment"):
                    if folder.id != account.calendar.id:
                        found.append(folder)

        self.call(collect)
        return found

    def resolve_calendar(self, calendar: str, *, allow_schedule: bool) -> tuple[Any, str]:
        """The calendar folder, or ``(None, address)`` for another person's free/busy."""
        value = (calendar or "").strip() or "primary"
        account_email = ews_settings(self._config).email
        if value.lower() in ("primary", account_email):
            return self.account.calendar, ""
        if "@" in value:
            if not allow_schedule:
                raise HTTPException(
                    400,
                    f"{LABEL}: events can only be saved in your own calendars; "
                    "use primary or one of your calendar names",
                )
            return None, value
        calendars = self._calendars()
        by_id = [folder for folder in calendars if folder.id == value]
        by_name = [
            folder for folder in calendars if str(folder.name or "").lower() == value.lower()
        ]
        if len(by_name) > 1 and not by_id:
            raise HTTPException(
                400, f"{LABEL}: more than one calendar has this name; use its calendar ID"
            )
        match = (by_id or by_name or [None])[0]
        if match is None:
            raise HTTPException(
                404, f"{LABEL}: calendar not found; use primary, a calendar name or its ID"
            )
        return match, ""

    def _calendar_view(
        self, folder: Any, lower: datetime, upper: datetime, zone: ZoneInfo, *, details: bool
    ) -> list[BusyEvent]:
        """Every blocking occurrence in the window, recurring ones expanded."""

        def view() -> list[Any]:
            query = folder.view(start=_ews_time(lower), end=_ews_time(upper))
            return [raise_failed(item) for item in query.only(*_VIEW_FIELDS)[: MAX_EVENTS + 1]]

        items = self.call(view)
        if len(items) > MAX_EVENTS:
            raise HTTPException(502, f"{LABEL}: too many events in this window; shorten the range")
        events = [busy_event(item, zone, details=details) for item in items]
        return [event for event in events if event and event.end > lower and event.start < upper]

    def _schedule(self, address: str, lower: datetime, upper: datetime) -> list[BusyEvent]:
        """Another person's free/busy, as their organization lets this mailbox see it."""

        def lookup() -> list[Any]:
            views = self.account.protocol.get_free_busy_info(
                accounts=[(address, "Required", False)],
                start=_ews_time(lower),
                end=_ews_time(upper),
                merged_free_busy_interval=30,
                requested_view="Detailed",
            )
            return list(views)

        views = self.call(lookup)
        view = views[0] if views else None
        if view is None or isinstance(view, Exception):
            raise HTTPException(
                403,
                f"{LABEL}: calendar availability is not accessible; check sharing permissions",
            )
        events: list[BusyEvent] = []
        for event in view.calendar_events or []:
            if str(event.busy_type or "NoData") not in BUSY_STATUSES:
                continue
            left, right = _utc(event.start, ZoneInfo("UTC")), _utc(event.end, ZoneInfo("UTC"))
            if right <= left:
                continue
            details = getattr(event, "details", None)
            subject = getattr(details, "subject", None) if details else None
            private = getattr(details, "is_private", False) if details else False
            title = subject if isinstance(subject, str) and not private else None
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
        folder, schedule = self.resolve_calendar(calendar_id, allow_schedule=True)
        if schedule:
            events = self._schedule(schedule, lower, upper)
        else:
            events = self._calendar_view(folder, lower, upper, zone, details=include_busy_details)
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

    def _event(self, event_id: str) -> Any:
        def fetch() -> Any:
            found = list(self.account.fetch(ids=[ItemId(id=event_id)]))
            return raise_failed(found[0]) if found else None

        item = self.call(fetch)
        if item is None:
            raise HTTPException(404, f"{LABEL}: calendar or event not found or not accessible")
        return item

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
        """Create an event, sending invitations when it has attendees, or update one."""
        if operation not in {"create", "update"}:
            raise HTTPException(400, f"{LABEL}: unsupported save operation")
        if operation == "create" and not (title.strip() and start.strip() and end.strip()):
            raise HTTPException(400, f"{LABEL}: create requires title, start and end")
        if operation == "update" and not event_id:
            raise HTTPException(400, f"{LABEL}: update requires an event ID")
        if bool(start.strip()) != bool(end.strip()):
            raise HTTPException(400, f"{LABEL}: supply both start and end when rescheduling")
        zone = calendar_zone(time_zone, LABEL)
        changes: dict[str, Any] = {}
        if title.strip():
            changes["subject"] = title
        if description.strip():
            changes["body"] = description
        if location.strip():
            changes["location"] = location
        if start.strip() and end.strip():
            start_at = parse_datetime(start, zone, LABEL)
            end_at = parse_datetime(end, zone, LABEL)
            if end_at.astimezone(timezone.utc) <= start_at.astimezone(timezone.utc):
                raise HTTPException(400, f"{LABEL}: event end must be after start")
            changes["start"] = _ews_time(start_at)
            changes["end"] = _ews_time(end_at)
        if attendees or isinstance(attendees, list):
            changes["required_attendees"] = parse_attendee_emails(attendees, LABEL) or None

        if operation == "create":
            folder, _schedule = self.resolve_calendar(calendar_id, allow_schedule=False)
            item = CalendarItem(account=self.account, folder=folder, **changes)
            invite = (
                SEND_TO_ALL_AND_SAVE_COPY if changes.get("required_attendees") else SEND_TO_NONE
            )
            self.call(lambda: item.save(send_meeting_invitations=invite))
        else:
            if not changes:
                raise HTTPException(400, f"{LABEL}: provide at least one field to update")
            item = self._event(event_id)
            for key, value in changes.items():
                setattr(item, key, value)
            meeting = bool(item.required_attendees or item.optional_attendees)
            invite = SEND_TO_ALL_AND_SAVE_COPY if meeting else SEND_TO_NONE
            self.call(
                lambda: item.save(update_fields=list(changes), send_meeting_invitations=invite)
            )
        result: dict[str, Any] = {
            "status": "success",
            "operation": operation,
            "event_id": str(item.id or ""),
            "teams_url": "",
            # Exchange Server has no Teams; the node reports it like an account without Teams.
            "teams_status": "unavailable" if operation == "create" and teams_meeting else "off",
            "web_link": str(item.web_client_read_form_query_string or ""),
            "event": event_output(item),
        }
        if operation == "create":
            result["calendar_id"] = (calendar_id or "").strip() or "primary"
        return result

    def delete_event(self, event_id: str) -> dict[str, Any]:
        """Delete an event; Exchange sends cancellations when the mailbox organized it."""
        if not event_id:
            raise HTTPException(400, f"{LABEL}: delete requires an event ID")
        item = self._event(event_id)
        self.call(lambda: item.delete(send_meeting_cancellations=SEND_TO_ALL_AND_SAVE_COPY))
        return {"status": "success", "operation": "delete", "event_id": event_id, "deleted": True}
