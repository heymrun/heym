"""Calendar request contracts, availability boundaries and invitation semantics."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

from app.services.google_meet_service import (
    GoogleMeetService,
    availability_window,
    parse_attendees,
    parse_datetime,
)


class TestAvailabilityWindow(unittest.TestCase):
    def test_november_six_defaults_to_december_first_in_selected_zone(self) -> None:
        now = datetime(2026, 11, 6, 10, 30, tzinfo=ZoneInfo("Europe/Berlin"))
        start, end = availability_window(time_zone="Europe/Berlin", now=now)
        self.assertEqual(start, now)
        self.assertEqual(end.isoformat(), "2026-12-01T00:00:00+01:00")

    def test_december_rolls_over_to_next_year(self) -> None:
        now = datetime(2026, 12, 31, 23, tzinfo=timezone.utc)
        self.assertEqual(availability_window(now=now)[1].isoformat(), "2027-01-01T00:00:00+00:00")

    def test_seven_days_and_sixty_days_are_allowed(self) -> None:
        for days in (7, 60):
            with self.subTest(days=days):
                start = datetime(2026, 11, 6, tzinfo=timezone.utc)
                bounds = availability_window(
                    start.isoformat(), (start + timedelta(days=days)).isoformat()
                )
                self.assertEqual(bounds[1] - bounds[0], timedelta(days=days))

    def test_sixty_calendar_days_across_dst_are_allowed(self) -> None:
        start, end = availability_window("2026-10-01", "2026-11-30", "Europe/Berlin")
        self.assertEqual((end - start).days, 60)

    def test_invalid_ranges_fail(self) -> None:
        for start, end, zone in (
            ("2026-11-06", "2027-01-06", "UTC"),
            ("2026-11-06", "2026-11-06", "UTC"),
            ("2026-11-06", "2026-11-05", "UTC"),
            ("yesterday", "2026-11-10", "UTC"),
            ("2026-11-06", "2026-11-10", "Invalid/Zone"),
        ):
            with self.subTest(start=start, end=end, zone=zone), self.assertRaises(HTTPException):
                availability_window(start, end, zone)

    def test_dst_nonexistent_and_ambiguous_local_times_require_offsets(self) -> None:
        for value in ("2026-03-29T02:30:00", "2026-10-25T02:30:00"):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                parse_datetime(value, ZoneInfo("Europe/Berlin"))
        self.assertEqual(
            parse_datetime("2026-10-25T02:30:00+01:00", ZoneInfo("Europe/Berlin")).fold, 1
        )


class TestAttendees(unittest.TestCase):
    def test_csv_json_and_arrays_deduplicate_addresses(self) -> None:
        for value in (
            "a@example.com; B@example.com\na@example.com",
            '["a@example.com", "B@example.com", "a@example.com"]',
            ["a@example.com", {"email": "B@example.com"}, "a@example.com"],
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    parse_attendees(value), [{"email": "a@example.com"}, {"email": "B@example.com"}]
                )

    def test_invalid_email_or_json_is_rejected(self) -> None:
        for value in ("[broken", "bad email", [None], [{"email": "bad"}], "[123]"):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                parse_attendees(value)


class TestGoogleMeetRequests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MagicMock()
        self.service = GoogleMeetService(
            "credential",
            {
                "access_token": "dummy-access",
                "refresh_token": "dummy-refresh",
                "client_id": "dummy-client",
                "client_secret": "dummy-secret",
                "token_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            },
            self.db,
        )
        self.requests: list[httpx.Request] = []
        self.response: dict = {}
        self.status = 200

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.status == 204:
                return httpx.Response(204)
            return httpx.Response(self.status, json=self.response)

        self.client = httpx.Client(transport=httpx.MockTransport(handle))
        self.addCleanup(self.client.close)
        self.patcher = patch("app.services.google_meet_service.httpx.request", self.client.request)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_read_subtracts_merged_clipped_busy_intervals(self) -> None:
        self.response = {
            "calendars": {
                "other@example.com": {
                    "busy": [
                        {"start": "2026-11-06T10:00:00Z", "end": "2026-11-06T11:00:00Z"},
                        {"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T10:30:00Z"},
                        {"start": "2026-11-05T23:00:00Z", "end": "2026-11-06T08:00:00Z"},
                        {"start": "2026-11-06T13:00:00Z", "end": "2026-11-07T01:00:00Z"},
                    ]
                }
            }
        }
        result = self.service.read_availability("other@example.com", "2026-11-06", "2026-11-07")
        self.assertEqual(
            result["available_slots"],
            [
                {"start": "2026-11-06T08:00:00+00:00", "end": "2026-11-06T09:00:00+00:00"},
                {"start": "2026-11-06T11:00:00+00:00", "end": "2026-11-06T13:00:00+00:00"},
            ],
        )
        self.assertEqual(result["count"], 2)
        request = self.requests[0]
        self.assertEqual(request.url.path, "/calendar/v3/freeBusy")
        self.assertEqual(request.headers["Authorization"], "Bearer dummy-access")
        self.assertNotIn("dummy-access", str(request.url))
        self.assertEqual(json.loads(request.content)["items"], [{"id": "other@example.com"}])

    def test_empty_calendar_is_entirely_free(self) -> None:
        self.response = {"calendars": {"primary": {"busy": []}}}
        result = self.service.read_availability(start="2026-11-06", end="2026-11-13")
        self.assertEqual(
            result["available_slots"], [{"start": result["start"], "end": result["end"]}]
        )

    def test_all_day_busy_produces_no_availability(self) -> None:
        self.response = {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2026-11-06T00:00:00Z", "end": "2026-11-07T00:00:00Z"},
                    ]
                }
            }
        }
        self.assertEqual(
            self.service.read_availability(start="2026-11-06", end="2026-11-07")["available_slots"],
            [],
        )

    def test_missing_or_inaccessible_calendar_fails_closed(self) -> None:
        for response in (
            {},
            {"calendars": {"primary": {}}},
            {"calendars": {"primary": {"errors": [{"reason": "notFound"}], "busy": []}}},
        ):
            with self.subTest(response=response):
                self.response = response
                with self.assertRaises(HTTPException):
                    self.service.read_availability(start="2026-11-06", end="2026-11-07")

    def test_oversized_range_never_calls_google(self) -> None:
        with self.assertRaises(HTTPException):
            self.service.read_availability(start="2026-11-06", end="2027-02-01")
        self.assertEqual(self.requests, [])

    def test_create_sends_meet_request_and_guest_invitations(self) -> None:
        self.response = {"id": "event-1", "hangoutLink": "https://meet.google.com/test"}
        result = self.service.save_event(
            "create",
            "primary",
            "",
            title='Meet "visitor"',
            description="First line\nSecond line",
            start="2026-11-10T14:00:00",
            end="2026-11-10T14:30:00",
            time_zone="Europe/Berlin",
            attendees="visitor@example.com",
        )
        request = self.requests[0]
        payload = json.loads(request.content)
        self.assertEqual(payload["summary"], 'Meet "visitor"')
        self.assertEqual(payload["description"], "First line\nSecond line")
        self.assertEqual(payload["attendees"], [{"email": "visitor@example.com"}])
        self.assertEqual(payload["start"]["dateTime"], "2026-11-10T14:00:00+01:00")
        self.assertEqual(
            payload["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"],
            "hangoutsMeet",
        )
        self.assertEqual(request.url.params["sendUpdates"], "all")
        self.assertEqual(request.url.params["conferenceDataVersion"], "1")
        self.assertEqual(result["event_id"], "event-1")
        self.assertEqual(result["meet_url"], "https://meet.google.com/test")

    def test_update_is_partial_preserves_conference_and_notifies_guests(self) -> None:
        self.response = {
            "id": "event-1",
            "conferenceData": {
                "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/kept"}]
            },
        }
        result = self.service.save_event(
            "update", "owner@example.com", "event-1", title="New title", attendees="[]"
        )
        request = self.requests[0]
        self.assertEqual(request.method, "PATCH")
        self.assertEqual(json.loads(request.content), {"summary": "New title", "attendees": []})
        self.assertEqual(request.url.params["sendUpdates"], "all")
        self.assertEqual(result["meet_url"], "https://meet.google.com/kept")

    def test_delete_notifies_all_guests(self) -> None:
        self.status = 204
        result = self.service.delete_event("owner@example.com", "event-1")
        self.assertEqual(self.requests[0].method, "DELETE")
        self.assertEqual(self.requests[0].url.params["sendUpdates"], "all")
        self.assertTrue(result["deleted"])

    def test_native_empty_attendee_list_clears_guests_on_update(self) -> None:
        self.response = {"id": "event-1"}
        self.service.save_event("update", "primary", "event-1", attendees=[])
        self.assertEqual(json.loads(self.requests[0].content), {"attendees": []})

    def test_non_object_calendar_response_is_rejected(self) -> None:
        self.response = []
        with self.assertRaises(HTTPException) as caught:
            self.service.read_availability(start="2026-11-06", end="2026-11-07")
        self.assertEqual(caught.exception.status_code, 502)

    def test_network_timeout_is_actionable(self) -> None:
        with (
            patch(
                "app.services.google_meet_service.httpx.request",
                side_effect=httpx.ReadTimeout("provider timeout"),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            self.service.read_availability(start="2026-11-06", end="2026-11-07")
        self.assertEqual(caught.exception.status_code, 502)

    def test_invalid_mutations_never_call_google(self) -> None:
        cases = [
            ("create", "", {}),
            ("update", "", {"title": "New"}),
            ("update", "event", {}),
            ("update", "event", {"start": "2026-11-06T10:00:00Z"}),
            (
                "create",
                "",
                {"title": "Bad", "start": "2026-11-06T10:00:00Z", "end": "2026-11-06T09:00:00Z"},
            ),
        ]
        for operation, event, kwargs in cases:
            with self.subTest(operation=operation, kwargs=kwargs), self.assertRaises(HTTPException):
                self.service.save_event(operation, "primary", event, **kwargs)
        with self.assertRaises(HTTPException):
            self.service.delete_event("primary", "")
        self.assertEqual(self.requests, [])

    def test_provider_errors_do_not_expose_response_body(self) -> None:
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                self.status, self.response = status, {"error": "dummy-secret"}
                with self.assertRaises(HTTPException) as caught:
                    self.service.delete_event("primary", "event")
                self.assertNotIn("dummy-secret", caught.exception.detail)

    def test_token_refresh_persists_encrypted_config(self) -> None:
        self.service._config["token_expiry"] = "expired"
        response = httpx.Response(
            200,
            json={"access_token": "fresh-dummy", "expires_in": 3600},
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
        )
        with (
            patch("app.services.google_meet_service.httpx.post", return_value=response) as refresh,
            patch(
                "app.services.google_meet_service.encrypt_config", return_value="encrypted-config"
            ),
        ):
            self.assertEqual(self.service.access_token(), "fresh-dummy")
        self.assertEqual(refresh.call_args.kwargs["data"]["refresh_token"], "dummy-refresh")
        self.assertEqual(
            self.db.query.return_value.filter.return_value.first.return_value.encrypted_config,
            "encrypted-config",
        )
        self.db.commit.assert_called_once()

    def test_revoked_refresh_is_actionable_and_redacted(self) -> None:
        self.service._config["token_expiry"] = "expired"
        response = httpx.Response(
            400,
            text="dummy-secret",
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
        )
        with (
            patch("app.services.google_meet_service.httpx.post", return_value=response),
            self.assertRaises(HTTPException) as caught,
        ):
            self.service.access_token()
        self.assertIn("reconnect", caught.exception.detail)
        self.assertNotIn("dummy-secret", caught.exception.detail)
        self.db.commit.assert_not_called()
