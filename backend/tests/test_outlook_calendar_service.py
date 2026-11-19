"""Outlook Calendar Graph client: availability, Teams invitations, calendars and safe errors."""

import unittest
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException

from app.services.outlook_calendar_service import (
    OUTLOOK_CALENDAR_SCOPES,
    OutlookCalendarService,
    graph_time,
    has_calendar_scope,
)
from app.services.outlook_service import GRAPH_BASE

FRESH = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
WINDOW = {"start": "2026-11-10T08:00:00+00:00", "end": "2026-11-11T08:00:00+00:00"}


def item(
    start: str, end: str, show_as: str = "busy", subject: str | None = "Standup", **extra: Any
) -> dict[str, Any]:
    """A calendarView occurrence as Graph returns it with outlook.timezone UTC."""
    event = {
        "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
        "end": {"dateTime": f"{end}.0000000", "timeZone": "UTC"},
        "showAs": show_as,
        "isCancelled": False,
        "isAllDay": False,
        **extra,
    }
    if subject is not None:
        event["subject"] = subject
    return event


class FakeGraph:
    """Routes Graph requests to handlers keyed by method and path, and records each call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.routes: dict[tuple[str, str], Callable[[dict[str, Any]], httpx.Response]] = {}

    def on(self, method: str, path: str, status: int = 200, body: Any = None) -> None:
        self.routes[(method, path)] = lambda _call: httpx.Response(
            status,
            json=body if body is not None else {},
            request=httpx.Request(method, f"{GRAPH_BASE}/{path}"),
        )

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        call = {"method": method, "url": url, **kwargs}
        self.calls.append(call)
        path = url.removeprefix(f"{GRAPH_BASE}/")
        handler = self.routes.get((method, path))
        if handler is None:
            raise AssertionError(f"unexpected Graph call {method} {url}")
        return handler(call)

    def paths(self) -> list[str]:
        return [
            f"{call['method']} {call['url'].removeprefix(GRAPH_BASE + '/')}" for call in self.calls
        ]


class CalendarTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = FakeGraph()
        patcher = patch("app.services.outlook_service.httpx.request", self.graph.request)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = MagicMock()
        self.service = OutlookCalendarService(
            "cred",
            {
                "client_id": "c",
                "client_secret": "s",
                "refresh_token": "r",
                "access_token": "a",
                "token_expiry": FRESH,
                "email_address": "me@contoso.com",
            },
            self.db,
        )


class ScopeAndTimeTests(unittest.TestCase):
    def test_scopes_ask_for_a_refresh_token_and_no_more_than_calendar_read_write(self) -> None:
        self.assertEqual(
            set(OUTLOOK_CALENDAR_SCOPES), {"offline_access", "User.Read", "Calendars.ReadWrite"}
        )
        self.assertTrue(has_calendar_scope("User.Read Calendars.ReadWrite"))
        self.assertTrue(has_calendar_scope("https://graph.microsoft.com/Calendars.ReadWrite"))
        self.assertFalse(has_calendar_scope("Calendars.Read Mail.ReadWrite"))
        self.assertFalse(has_calendar_scope(""))

    def test_graph_times_with_seven_fraction_digits_and_iana_zones_parse(self) -> None:
        self.assertEqual(
            graph_time({"dateTime": "2026-11-10T09:30:00.1234567", "timeZone": "UTC"}),
            datetime(2026, 11, 10, 9, 30, 0, 123456, tzinfo=timezone.utc),
        )
        self.assertEqual(
            graph_time({"dateTime": "2026-11-10T10:00:00", "timeZone": "Europe/Berlin"}),
            datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc),
        )
        for bad in (
            None,
            {"dateTime": "soon"},
            {"dateTime": "2026-11-10T10:00:00", "timeZone": "Mars"},
        ):
            with self.subTest(value=bad), self.assertRaises(HTTPException) as caught:
                graph_time(bad)
            self.assertEqual(caught.exception.status_code, 502)


class AvailabilityTests(CalendarTestCase):
    def test_primary_read_merges_blocking_events_and_skips_free_time(self) -> None:
        self.graph.on(
            "GET",
            "calendar/calendarView",
            body={
                "value": [
                    item("2026-11-10T09:00:00", "2026-11-10T10:00:00"),
                    item("2026-11-10T09:30:00", "2026-11-10T10:30:00", "tentative"),
                    item("2026-11-10T12:00:00", "2026-11-10T13:00:00", "oof"),
                    item("2026-11-10T14:00:00", "2026-11-10T15:00:00", "free"),
                    item("2026-11-10T15:00:00", "2026-11-10T16:00:00", "workingElsewhere"),
                    item("2026-11-10T17:00:00", "2026-11-10T18:00:00", isCancelled=True),
                    item("2026-11-10T19:00:00", "2026-11-10T19:00:00"),
                ]
            },
        )

        result = self.service.read_availability("primary", WINDOW["start"], WINDOW["end"], "UTC")

        self.assertEqual(
            result["busy_slots"],
            [
                {"start": "2026-11-10T09:00:00+00:00", "end": "2026-11-10T10:30:00+00:00"},
                {"start": "2026-11-10T12:00:00+00:00", "end": "2026-11-10T13:00:00+00:00"},
            ],
        )
        self.assertEqual(
            result["available_slots"],
            [
                {"start": "2026-11-10T08:00:00+00:00", "end": "2026-11-10T09:00:00+00:00"},
                {"start": "2026-11-10T10:30:00+00:00", "end": "2026-11-10T12:00:00+00:00"},
                {"start": "2026-11-10T13:00:00+00:00", "end": "2026-11-11T08:00:00+00:00"},
            ],
        )
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["calendar_id"], "primary")
        call = self.graph.calls[0]
        self.assertEqual(call["params"]["$select"], "start,end,showAs,isCancelled,isAllDay")
        self.assertEqual(call["params"]["startDateTime"], "2026-11-10T08:00:00Z")
        self.assertEqual(call["params"]["endDateTime"], "2026-11-11T08:00:00Z")
        prefer = call["headers"]["Prefer"]
        self.assertIn('IdType="ImmutableId"', prefer)
        self.assertIn('outlook.timezone="UTC"', prefer)

    def test_busy_details_keep_each_event_title_and_attendees_without_rooms(self) -> None:
        self.graph.on(
            "GET",
            "calendar/calendarView",
            body={
                "value": [
                    item(
                        "2026-11-10T09:00:00",
                        "2026-11-10T10:00:00",
                        subject="Planning",
                        attendees=[
                            {"type": "required", "emailAddress": {"address": "a@contoso.com"}},
                            {"type": "resource", "emailAddress": {"address": "room@contoso.com"}},
                            {"type": "optional", "emailAddress": {"address": "b@contoso.com"}},
                        ],
                    ),
                    item(
                        "2026-11-10T09:30:00", "2026-11-10T11:00:00", subject="Focus", attendees=[]
                    ),
                ]
            },
        )

        result = self.service.read_availability(
            "primary", WINDOW["start"], WINDOW["end"], "UTC", include_busy_details=True
        )

        self.assertEqual(
            self.graph.calls[0]["params"]["$select"],
            "start,end,showAs,isCancelled,isAllDay,subject,attendees",
        )
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-10T09:00:00+00:00",
                    "end": "2026-11-10T10:00:00+00:00",
                    "title": "Planning",
                    "attendees": ["a@contoso.com", "b@contoso.com"],
                },
                {
                    "start": "2026-11-10T09:30:00+00:00",
                    "end": "2026-11-10T11:00:00+00:00",
                    "title": "Focus",
                    "attendees": [],
                },
            ],
        )
        self.assertEqual(len(result["available_slots"]), 2)

    def test_an_all_day_event_blocks_the_whole_day_in_the_selected_zone(self) -> None:
        self.graph.on(
            "GET",
            "calendar/calendarView",
            body={
                "value": [
                    item("2026-11-12T00:00:00", "2026-11-13T00:00:00", isAllDay=True, showAs="oof")
                ]
            },
        )

        result = self.service.read_availability(
            "primary", "2026-11-12T00:00:00", "2026-11-14T00:00:00", "Europe/Berlin"
        )

        self.assertEqual(
            result["busy_slots"],
            [{"start": "2026-11-12T00:00:00+01:00", "end": "2026-11-13T00:00:00+01:00"}],
        )
        self.assertEqual(
            result["available_slots"],
            [{"start": "2026-11-13T00:00:00+01:00", "end": "2026-11-14T00:00:00+01:00"}],
        )

    def test_all_day_events_around_a_day_without_midnight_are_read(self) -> None:
        # Africa/Cairo goes from 00:00 to 01:00 on 2026-04-24: that day starts at 01:00.
        self.graph.on(
            "GET",
            "calendar/calendarView",
            body={
                "value": [
                    item("2026-04-23T00:00:00", "2026-04-24T00:00:00", isAllDay=True, showAs="oof"),
                    item("2026-04-24T00:00:00", "2026-04-25T00:00:00", isAllDay=True, showAs="oof"),
                ]
            },
        )

        result = self.service.read_availability(
            "primary", "2026-04-22T00:00:00", "2026-04-26T00:00:00", "Africa/Cairo"
        )

        self.assertEqual(
            result["busy_slots"],
            [{"start": "2026-04-23T00:00:00+02:00", "end": "2026-04-25T00:00:00+03:00"}],
        )
        self.assertEqual(
            result["available_slots"],
            [
                {"start": "2026-04-22T00:00:00+02:00", "end": "2026-04-23T00:00:00+02:00"},
                {"start": "2026-04-25T00:00:00+03:00", "end": "2026-04-26T00:00:00+03:00"},
            ],
        )

    def test_every_page_is_read_and_a_next_link_off_graph_is_refused(self) -> None:
        next_link = f"{GRAPH_BASE}/calendar/calendarView?$skiptoken=2"
        self.graph.on(
            "GET",
            "calendar/calendarView",
            body={
                "value": [item("2026-11-10T09:00:00", "2026-11-10T10:00:00")],
                "@odata.nextLink": next_link,
            },
        )
        self.graph.on(
            "GET",
            "calendar/calendarView?$skiptoken=2",
            body={"value": [item("2026-11-10T11:00:00", "2026-11-10T12:00:00")]},
        )

        result = self.service.read_availability("primary", WINDOW["start"], WINDOW["end"])

        self.assertEqual(len(result["busy_slots"]), 2)
        self.assertIsNone(self.graph.calls[1]["params"])

        self.graph.calls.clear()
        self.graph.on(
            "GET",
            "calendar/calendarView",
            body={"value": [], "@odata.nextLink": "https://evil.example/steal"},
        )
        with self.assertRaises(HTTPException) as caught:
            self.service.read_availability("primary", WINDOW["start"], WINDOW["end"])
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(len(self.graph.calls), 1)

    def test_a_calendar_name_resolves_to_its_id_and_ambiguous_or_missing_names_fail(self) -> None:
        self.graph.on(
            "GET",
            "calendars",
            body={
                "value": [
                    {"id": "AAA/1=", "name": "Calendar"},
                    {"id": "BBB", "name": "Work"},
                    {"id": "CCC", "name": "Shared"},
                    {"id": "DDD", "name": "shared"},
                ]
            },
        )
        self.graph.on("GET", "calendars/BBB/calendarView", body={"value": []})
        self.graph.on("GET", "calendars/AAA%2F1%3D/calendarView", body={"value": []})

        self.service.read_availability("work", WINDOW["start"], WINDOW["end"])
        self.service.read_availability("AAA/1=", WINDOW["start"], WINDOW["end"])
        self.assertIn("GET calendars/BBB/calendarView", self.graph.paths())
        self.assertIn("GET calendars/AAA%2F1%3D/calendarView", self.graph.paths())

        for name, status in (("Shared", 400), ("Holidays", 404)):
            with self.subTest(name=name), self.assertRaises(HTTPException) as caught:
                self.service.read_availability(name, WINDOW["start"], WINDOW["end"])
            self.assertEqual(caught.exception.status_code, status)

    def test_the_account_address_reads_the_primary_calendar(self) -> None:
        self.graph.on("GET", "calendar/calendarView", body={"value": []})

        self.service.read_availability("ME@contoso.com", WINDOW["start"], WINDOW["end"])

        self.assertEqual(self.graph.paths(), ["GET calendar/calendarView"])

    def test_a_colleague_address_reads_free_busy_through_get_schedule(self) -> None:
        self.graph.on(
            "POST",
            "calendar/getSchedule",
            body={
                "value": [
                    {
                        "scheduleId": "Colleague@Contoso.com",
                        "scheduleItems": [
                            {
                                "status": "busy",
                                "subject": "Board review",
                                "isPrivate": False,
                                "start": {
                                    "dateTime": "2026-11-10T09:00:00.0000000",
                                    "timeZone": "UTC",
                                },
                                "end": {
                                    "dateTime": "2026-11-10T10:00:00.0000000",
                                    "timeZone": "UTC",
                                },
                            },
                            {
                                "status": "busy",
                                "subject": "Doctor",
                                "isPrivate": True,
                                "start": {
                                    "dateTime": "2026-11-10T12:00:00.0000000",
                                    "timeZone": "UTC",
                                },
                                "end": {
                                    "dateTime": "2026-11-10T13:00:00.0000000",
                                    "timeZone": "UTC",
                                },
                            },
                            {
                                "status": "free",
                                "start": {
                                    "dateTime": "2026-11-10T14:00:00.0000000",
                                    "timeZone": "UTC",
                                },
                                "end": {
                                    "dateTime": "2026-11-10T15:00:00.0000000",
                                    "timeZone": "UTC",
                                },
                            },
                        ],
                    }
                ]
            },
        )

        result = self.service.read_availability(
            "colleague@contoso.com",
            WINDOW["start"],
            WINDOW["end"],
            include_busy_details=True,
        )

        body = self.graph.calls[0]["json"]
        self.assertEqual(body["schedules"], ["colleague@contoso.com"])
        self.assertEqual(body["startTime"], {"dateTime": "2026-11-10T08:00:00", "timeZone": "UTC"})
        self.assertEqual(
            [(slot["title"], slot["attendees"]) for slot in result["busy_slots"]],
            [("Board review", None), (None, None)],
        )
        self.assertEqual(result["count"], 3)

    def test_inaccessible_schedules_fail_instead_of_reading_as_free(self) -> None:
        for body in (
            {"value": [{"scheduleId": "x@contoso.com", "error": {"message": "denied"}}]},
            {"value": []},
            {"value": [{"scheduleId": "x@contoso.com"}]},
        ):
            with self.subTest(body=body):
                self.graph.on("POST", "calendar/getSchedule", body=body)
                with self.assertRaises(HTTPException) as caught:
                    self.service.read_availability("x@contoso.com", WINDOW["start"], WINDOW["end"])
                self.assertEqual(caught.exception.status_code, 403)
                self.assertNotIn("denied", caught.exception.detail)

    def test_a_window_over_sixty_days_is_rejected_before_calling_graph(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.service.read_availability("primary", "2026-11-01", "2027-01-15")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("Outlook Calendar", caught.exception.detail)
        self.assertEqual(self.graph.calls, [])


class SaveEventTests(CalendarTestCase):
    def _created(self, call: dict[str, Any]) -> httpx.Response:
        body = call["json"]
        event = {
            "id": "EVT-1",
            "webLink": "https://outlook.office365.com/owa/?itemid=EVT-1",
            "isOnlineMeeting": body.get("isOnlineMeeting", False),
        }
        if body.get("isOnlineMeeting"):
            event["onlineMeeting"] = {"joinUrl": "https://teams.microsoft.com/l/meetup-join/1"}
        return httpx.Response(201, json=event, request=httpx.Request("POST", call["url"]))

    def test_create_adds_a_teams_meeting_invites_attendees_and_sends_utc_times(self) -> None:
        self.graph.on(
            "GET",
            "calendar",
            body={"allowedOnlineMeetingProviders": ["teamsForBusiness"]},
        )
        self.graph.routes[("POST", "calendar/events")] = self._created

        result = self.service.save_event(
            "create",
            "primary",
            "",
            title="Intro call",
            description="Booked through Heym",
            start="2026-11-10T14:00:00",
            end="2026-11-10T14:30:00",
            time_zone="Europe/Berlin",
            attendees="visitor@example.com; Visitor@example.com, other@example.com",
            location="Room 4",
        )

        body = self.graph.calls[1]["json"]
        self.assertEqual(body["subject"], "Intro call")
        self.assertEqual(body["body"], {"contentType": "text", "content": "Booked through Heym"})
        self.assertEqual(body["location"], {"displayName": "Room 4"})
        self.assertEqual(body["start"], {"dateTime": "2026-11-10T13:00:00", "timeZone": "UTC"})
        self.assertEqual(body["end"], {"dateTime": "2026-11-10T13:30:00", "timeZone": "UTC"})
        self.assertEqual(
            body["attendees"],
            [
                {"emailAddress": {"address": "visitor@example.com"}, "type": "required"},
                {"emailAddress": {"address": "other@example.com"}, "type": "required"},
            ],
        )
        self.assertTrue(body["isOnlineMeeting"])
        self.assertEqual(body["onlineMeetingProvider"], "teamsForBusiness")
        self.assertEqual(result["event_id"], "EVT-1")
        self.assertEqual(result["teams_url"], "https://teams.microsoft.com/l/meetup-join/1")
        self.assertEqual(result["teams_status"], "ready")
        self.assertEqual(result["calendar_id"], "primary")
        self.assertEqual(result["web_link"], "https://outlook.office365.com/owa/?itemid=EVT-1")

    def test_accounts_without_teams_get_a_plain_event_marked_unavailable(self) -> None:
        self.graph.on("GET", "calendar", body={"allowedOnlineMeetingProviders": []})
        self.graph.routes[("POST", "calendar/events")] = self._created

        result = self.service.save_event(
            "create",
            "primary",
            "",
            title="Coffee",
            start="2026-11-10T14:00:00Z",
            end="2026-11-10T14:30:00Z",
        )

        self.assertNotIn("isOnlineMeeting", self.graph.calls[1]["json"])
        self.assertEqual(result["teams_status"], "unavailable")
        self.assertEqual(result["teams_url"], "")

    def test_turning_teams_off_skips_the_provider_check(self) -> None:
        self.graph.routes[("POST", "calendar/events")] = self._created

        result = self.service.save_event(
            "create",
            "primary",
            "",
            title="In person",
            start="2026-11-10T14:00:00Z",
            end="2026-11-10T14:30:00Z",
            teams_meeting=False,
        )

        self.assertEqual(self.graph.paths(), ["POST calendar/events"])
        self.assertEqual(result["teams_status"], "off")

    def test_events_are_never_created_in_another_persons_calendar(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.service.save_event(
                "create",
                "boss@contoso.com",
                "",
                title="Hold",
                start="2026-11-10T14:00:00Z",
                end="2026-11-10T14:30:00Z",
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.graph.calls, [])

    def test_create_requires_title_and_both_times(self) -> None:
        for fields in (
            {"title": "", "start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z"},
            {"title": "x", "start": "2026-11-10T14:00:00Z", "end": ""},
            {"title": "x", "start": "2026-11-10T15:00:00Z", "end": "2026-11-10T14:00:00Z"},
        ):
            with self.subTest(fields=fields), self.assertRaises(HTTPException) as caught:
                self.service.save_event("create", "primary", "", **fields)
            self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.graph.calls, [])

    def test_update_patches_only_supplied_fields_and_can_clear_guests(self) -> None:
        self.graph.on(
            "PATCH",
            "events/EVT%2F1",
            body={"id": "EVT/1", "isOnlineMeeting": True, "onlineMeeting": None},
        )

        result = self.service.save_event(
            "update", "ignored", "EVT/1", title="Renamed", attendees="[]"
        )

        call = self.graph.calls[0]
        self.assertEqual(call["json"], {"subject": "Renamed", "attendees": []})
        self.assertEqual(result["teams_status"], "pending")
        self.assertNotIn("calendar_id", result)

    def test_update_needs_an_event_a_change_and_both_times(self) -> None:
        for event_id, fields in (
            ("", {"title": "x"}),
            ("EVT", {}),
            ("EVT", {"start": "2026-11-10T14:00:00Z"}),
        ):
            with self.subTest(event_id=event_id, fields=fields):
                with self.assertRaises(HTTPException) as caught:
                    self.service.save_event("update", "primary", event_id, **fields)
                self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.graph.calls, [])

    def test_delete_quotes_the_event_id(self) -> None:
        self.graph.routes[("DELETE", "events/A%2FB%3D")] = lambda call: httpx.Response(
            204, request=httpx.Request("DELETE", call["url"])
        )

        result = self.service.delete_event("A/B=")

        self.assertEqual(
            result,
            {"status": "success", "operation": "delete", "event_id": "A/B=", "deleted": True},
        )
        with self.assertRaises(HTTPException):
            self.service.delete_event("")

    def test_graph_errors_keep_the_status_and_never_echo_the_body(self) -> None:
        self.graph.on(
            "DELETE",
            "events/EVT",
            status=403,
            body={"error": {"message": "secret-detail boss@contoso.com"}},
        )

        with self.assertRaises(HTTPException) as caught:
            self.service.delete_event("EVT")

        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("Calendars.ReadWrite", caught.exception.detail)
        self.assertNotIn("secret-detail", caught.exception.detail)


class TokenRefreshTests(unittest.TestCase):
    def test_an_expired_token_is_refreshed_with_calendar_scopes_and_the_rotation_saved(
        self,
    ) -> None:
        db = MagicMock()
        stored = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = stored
        service = OutlookCalendarService(
            "cred",
            {
                "client_id": "c",
                "client_secret": "s",
                "refresh_token": "old",
                "tenant": "contoso.com",
                "token_expiry": "2020-01-01T00:00:00+00:00",
            },
            db,
        )
        response = httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600},
            request=httpx.Request("POST", "https://login.microsoftonline.com"),
        )
        with (
            patch("app.services.outlook_service.httpx.post", return_value=response) as post,
            patch("app.services.outlook_service.encrypt_config", return_value="enc") as encrypt,
        ):
            self.assertEqual(service.access_token(), "new-access")

        self.assertEqual(
            post.call_args.args[0],
            "https://login.microsoftonline.com/contoso.com/oauth2/v2.0/token",
        )
        self.assertEqual(
            post.call_args.kwargs["data"]["scope"], "offline_access User.Read Calendars.ReadWrite"
        )
        self.assertEqual(encrypt.call_args.args[0]["refresh_token"], "new-refresh")
        self.assertEqual(stored.encrypted_config, "enc")
        db.commit.assert_called_once()

    def test_a_failed_refresh_names_the_calendar_credential(self) -> None:
        service = OutlookCalendarService("cred", {"token_expiry": ""}, MagicMock())
        with patch("app.services.outlook_service.httpx.request") as request:
            with self.assertRaises(HTTPException) as caught:
                service.read_availability("primary", WINDOW["start"], WINDOW["end"])
        self.assertEqual(caught.exception.status_code, 401)
        self.assertTrue(caught.exception.detail.startswith("Outlook Calendar:"))
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
