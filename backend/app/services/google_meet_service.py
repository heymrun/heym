"""Google Calendar events with Meet conferences and bounded availability reads."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Credential
from app.services import calendar_slots
from app.services.calendar_slots import (
    MAX_AVAILABILITY_DAYS,
    format_intervals,
    free_intervals,
    merge_intervals,
)
from app.services.encryption import encrypt_config

CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_MEET_SCOPE = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.events.freebusy"
)
_LABEL = "Google Meet"

__all__ = [
    "MAX_AVAILABILITY_DAYS",
    "GoogleMeetService",
    "availability_window",
    "calendar_zone",
    "parse_attendees",
    "parse_datetime",
]


def calendar_zone(name: str) -> ZoneInfo:
    """Validate an IANA time zone before interpreting local dates."""
    return calendar_slots.calendar_zone(name, _LABEL)


def parse_datetime(value: str, zone: ZoneInfo) -> datetime:
    """Interpret ISO dates/datetimes in the selected zone and retain explicit offsets."""
    return calendar_slots.parse_datetime(value, zone, _LABEL)


def availability_window(
    start: str = "", end: str = "", time_zone: str = "UTC", *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Default to now through next month's first midnight, with a 60-day maximum."""
    return calendar_slots.availability_window(start, end, time_zone, _LABEL, now=now)


def parse_attendees(value: str | list[Any]) -> list[dict[str, str]]:
    """Accept email lists as JSON arrays or comma/semicolon/newline separated text."""
    return [{"email": email} for email in calendar_slots.parse_attendee_emails(value, _LABEL)]


class GoogleMeetService:
    """Synchronous Calendar API client used by the modular node handler."""

    def __init__(self, credential_id: str, config: dict[str, Any], db: Session) -> None:
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

    def access_token(self) -> str:
        """Refresh expired tokens and persist only encrypted credential configuration."""
        try:
            expiry = datetime.fromisoformat(self._config.get("token_expiry", ""))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            expired = expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc) + timedelta(
                seconds=60
            )
        except (ValueError, TypeError):
            expired = True
        if expired:
            if not all(
                self._config.get(key) for key in ("refresh_token", "client_id", "client_secret")
            ):
                raise HTTPException(400, "Google Meet: reconnect the credential in Credentials")
            try:
                response = httpx.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "refresh_token",
                        **{
                            key: self._config[key]
                            for key in ("refresh_token", "client_id", "client_secret")
                        },
                    },
                    timeout=30,
                )
                response.raise_for_status()
                tokens = response.json()
                self._config["access_token"] = tokens["access_token"]
                self._config["token_expiry"] = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=int(tokens.get("expires_in", 3600)))
                ).isoformat()
                if tokens.get("refresh_token"):
                    self._config["refresh_token"] = tokens["refresh_token"]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise HTTPException(
                    400, "Google Meet: token refresh failed; reconnect the credential"
                ) from exc
            credential = (
                self._db.query(Credential).filter(Credential.id == self._credential_id).first()
            )
            if credential:
                credential.encrypted_config = encrypt_config(self._config)
                self._db.commit()
        token = str(self._config.get("access_token") or "").strip()
        if not token:
            raise HTTPException(400, "Google Meet: reconnect the credential in Credentials")
        return token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{CALENDAR_BASE}/{path}",
                headers={"Authorization": f"Bearer {self.access_token()}"},
                timeout=30,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Google Meet: Google Calendar could not be reached") from exc
        if response.is_error:
            # Never persist provider response bodies: they can contain credentials or PII.
            detail = {
                401: "credential expired; reconnect it",
                403: "calendar access denied; check sharing and OAuth permissions",
                404: "calendar or event not found or not accessible",
                429: "Google Calendar rate limit reached; retry later",
            }.get(response.status_code, "Google Calendar rejected the request")
            raise HTTPException(response.status_code, f"Google Meet: {detail}")
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(502, "Google Meet: invalid Google Calendar response") from exc
        if not isinstance(data, dict):
            raise HTTPException(502, "Google Meet: invalid Google Calendar response")
        return data

    def read_availability(
        self,
        calendar_id: str = "primary",
        start: str = "",
        end: str = "",
        time_zone: str = "UTC",
        *,
        include_busy_details: bool = False,
    ) -> dict[str, Any]:
        """Return free intervals, failing closed on per-calendar FreeBusy errors."""
        enabled = bool(include_busy_details)
        start_at, end_at = availability_window(start, end, time_zone)
        result = self._request(
            "POST",
            "freeBusy",
            json={
                "timeMin": start_at.isoformat(),
                "timeMax": end_at.isoformat(),
                "timeZone": time_zone,
                "items": [{"id": calendar_id}],
            },
        )
        calendars = result.get("calendars")
        calendar = calendars.get(calendar_id) if isinstance(calendars, dict) else None
        if (
            not isinstance(calendar, dict)
            or calendar.get("errors")
            or not isinstance(calendar.get("busy"), list)
        ):
            raise HTTPException(
                403,
                "Google Meet: calendar availability is not accessible; check sharing permissions",
            )
        zone = calendar_zone(time_zone)
        # UTC comparisons handle offset transitions and overlapping/all-day busy periods.
        lower, upper = start_at.astimezone(timezone.utc), end_at.astimezone(timezone.utc)
        busy: list[tuple[datetime, datetime]] = []
        try:
            for item in calendar["busy"]:
                left = parse_datetime(item["start"], zone).astimezone(timezone.utc)
                right = parse_datetime(item["end"], zone).astimezone(timezone.utc)
                if right <= left:
                    raise HTTPException(
                        502, "Google Meet: invalid busy interval from Google Calendar"
                    )
                if right > lower and left < upper:
                    busy.append((max(left, lower), min(right, upper)))
        except (KeyError, TypeError) as exc:
            raise HTTPException(502, "Google Meet: invalid availability response") from exc
        merged = merge_intervals(busy)
        free = free_intervals(merged, lower, upper)
        busy_slots: list[dict[str, Any]] = list(format_intervals(merged, zone))
        if enabled and merged:
            from app.services.google_meet_busy_titles import label_busy_intervals, read_busy_events

            busy_slots = label_busy_intervals(
                merged, read_busy_events(self._request, calendar_id, lower, upper), zone
            )

        return {
            "status": "success",
            "operation": "read",
            "calendar_id": calendar_id,
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
    ) -> dict[str, Any]:
        """Create a Meet invitation or patch supplied fields, notifying all guests."""
        if operation not in {"create", "update"}:
            raise HTTPException(400, "Google Meet: unsupported save operation")
        if operation == "create" and not (title.strip() and start.strip() and end.strip()):
            raise HTTPException(400, "Google Meet: create requires title, start and end")
        if operation == "update" and not event_id:
            raise HTTPException(400, "Google Meet: update requires an event ID")
        zone = calendar_zone(time_zone)
        body: dict[str, Any] = {}
        for key, value in (
            ("summary", title),
            ("description", description),
            ("location", location),
        ):
            if value.strip():
                body[key] = value
        if bool(start.strip()) != bool(end.strip()):
            raise HTTPException(400, "Google Meet: supply both start and end when rescheduling")
        if start.strip() and end.strip():
            start_at, end_at = parse_datetime(start, zone), parse_datetime(end, zone)
            if end_at.astimezone(timezone.utc) <= start_at.astimezone(timezone.utc):
                raise HTTPException(400, "Google Meet: event end must be after start")
            body.update(
                {
                    "start": {"dateTime": start_at.isoformat(), "timeZone": time_zone},
                    "end": {"dateTime": end_at.isoformat(), "timeZone": time_zone},
                }
            )
        if attendees or isinstance(attendees, list):
            body["attendees"] = parse_attendees(attendees)
        path = f"calendars/{quote(calendar_id, safe='')}/events"
        if operation == "create":
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        elif not body:
            raise HTTPException(400, "Google Meet: provide at least one field to update")
        else:
            path += f"/{quote(event_id, safe='')}"
        event = self._request(
            "POST" if operation == "create" else "PATCH",
            path,
            params={"conferenceDataVersion": 1, "sendUpdates": "all"},
            json=body,
        )
        conference = event.get("conferenceData", {})
        return {
            "status": "success",
            "operation": operation,
            "calendar_id": calendar_id,
            "event_id": event.get("id", ""),
            "event": event,
            "meet_url": event.get("hangoutLink")
            or next(
                (
                    item.get("uri", "")
                    for item in conference.get("entryPoints", [])
                    if item.get("entryPointType") == "video"
                ),
                "",
            ),
            "conference_status": conference.get("createRequest", {})
            .get("status", {})
            .get("statusCode", ""),
        }

    def delete_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        """Delete an event and send cancellation updates to all attendees."""
        if not event_id:
            raise HTTPException(400, "Google Meet: delete requires an event ID")
        self._request(
            "DELETE",
            f"calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
            params={"sendUpdates": "all"},
        )
        return {
            "status": "success",
            "operation": "delete",
            "calendar_id": calendar_id,
            "event_id": event_id,
            "deleted": True,
        }
