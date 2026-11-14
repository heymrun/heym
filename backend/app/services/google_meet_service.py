"""Google Calendar events with Meet conferences and bounded availability reads."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Credential
from app.services.encryption import encrypt_config

CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_MEET_SCOPE = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.events.freebusy"
)
MAX_AVAILABILITY_DAYS = 60


def calendar_zone(name: str) -> ZoneInfo:
    """Validate an IANA time zone before interpreting local dates."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(400, "Google Meet: use a valid IANA time zone") from exc


def parse_datetime(value: str, zone: ZoneInfo) -> datetime:
    """Interpret ISO dates/datetimes in the selected zone and retain explicit offsets."""
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, "Google Meet: dates must use ISO 8601 format")
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Google Meet: dates must use ISO 8601 format") from exc
    if result.tzinfo is not None:
        return result.astimezone(zone)
    result = result.replace(tzinfo=zone)
    if result.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != result.replace(
        tzinfo=None
    ):
        raise HTTPException(400, "Google Meet: this local time does not exist; use an offset")
    if result.utcoffset() != result.replace(fold=1).utcoffset():
        raise HTTPException(400, "Google Meet: ambiguous local time; include a UTC offset")
    return result


def availability_window(
    start: str = "", end: str = "", time_zone: str = "UTC", *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Default to now through next month's first midnight, with a 60-day maximum."""
    zone = calendar_zone(time_zone)
    start_at = parse_datetime(start, zone) if start.strip() else (now or datetime.now(zone))
    start_at = start_at.astimezone(zone)
    end_at = (
        parse_datetime(end, zone)
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
        raise HTTPException(400, "Google Meet: end must follow start by at most 60 days")
    return start_at, end_at


def parse_attendees(value: str | list[Any]) -> list[dict[str, str]]:
    """Accept email lists as JSON arrays or comma/semicolon/newline separated text."""
    if isinstance(value, str):
        if value.strip().startswith("["):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise HTTPException(400, "Google Meet: invalid attendee JSON array") from exc
        else:
            value = [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]
    if not isinstance(value, list):
        raise HTTPException(400, "Google Meet: attendees must be a list of email addresses")
    attendees: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        email = item.get("email", "") if isinstance(item, dict) else item
        if not isinstance(email, str) or not re.fullmatch(
            r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", email.strip()
        ):
            raise HTTPException(400, "Google Meet: each attendee must have a valid email address")
        email = email.strip()
        if email.lower() not in seen:
            attendees.append({"email": email})
            seen.add(email.lower())
    return attendees


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
        include_busy_details: bool | None = None,
        include_busy_titles: bool | None = None,
    ) -> dict[str, Any]:
        """Return free intervals, failing closed on per-calendar FreeBusy errors."""
        enabled = (
            include_busy_details
            if include_busy_details is not None
            else (include_busy_titles if include_busy_titles is not None else False)
        )
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
        merged: list[tuple[datetime, datetime]] = []
        for left, right in sorted(busy):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        free: list[tuple[datetime, datetime]] = []
        cursor = lower
        for left, right in merged:
            if cursor < left:
                free.append((cursor, left))
            cursor = right
        if cursor < upper:
            free.append((cursor, upper))

        def intervals(values: list[tuple[datetime, datetime]]) -> list[dict[str, str]]:
            return [
                {"start": a.astimezone(zone).isoformat(), "end": b.astimezone(zone).isoformat()}
                for a, b in values
            ]

        busy_slots: list[dict[str, Any]] = list(intervals(merged))
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
            "available_slots": intervals(free),
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
