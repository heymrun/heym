"""Opt-in busy titles preserve availability and Google's detail visibility."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException

from app.services.google_meet_service import GoogleMeetService


def timed_event(start: str, end: str, title: str | None = "Team meeting", **extra: object) -> dict:
    """Build an occurrence from the documented Calendar Events list contract."""
    event = {"start": {"dateTime": start}, "end": {"dateTime": end}, **extra}
    if title is not None:
        event["summary"] = title
    return event


class TestGoogleMeetBusyTitles(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T12:00:00Z"}]
        self.pages: list[dict] = [
            {
                "timeZone": "UTC",
                "items": [timed_event("2026-11-06T09:00:00Z", "2026-11-06T12:00:00Z")],
            }
        ]
        self.events_status = 200
        self.page_index = 0

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"calendars": {"primary": {"busy": self.busy}}})
            page = self.pages[min(self.page_index, len(self.pages) - 1)]
            self.page_index += 1
            return httpx.Response(self.events_status, json=page)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        self.addCleanup(client.close)
        patcher = patch("app.services.google_meet_service.httpx.request", client.request)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = GoogleMeetService(
            "credential",
            {
                "access_token": "dummy-access",
                "token_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            },
            MagicMock(),
        )

    def read(self, **kwargs: object) -> dict:
        """Read one day, optionally changing the flag and display zone."""
        return self.service.read_availability(
            start="2026-11-06T00:00:00Z", end="2026-11-07T00:00:00Z", **kwargs
        )

    def test_default_and_explicit_false_never_fetch_or_expose_titles(self) -> None:
        for kwargs in ({}, {"include_busy_titles": False}):
            with self.subTest(kwargs=kwargs):
                result = self.read(**kwargs)
                self.assertEqual(
                    result["busy_slots"],
                    [{"start": "2026-11-06T09:00:00+00:00", "end": "2026-11-06T12:00:00+00:00"}],
                )
                self.assertNotIn("Team meeting", str(result))
        self.assertTrue(all(request.method == "POST" for request in self.requests))

    def test_enabled_returns_actual_title_and_preserves_available_slots(self) -> None:
        title = 'Design review: "release"\nFollow-up'
        self.pages[0]["items"][0]["summary"] = title
        original, enriched = self.read(), self.read(include_busy_titles=True)
        self.assertEqual(enriched["available_slots"], original["available_slots"])
        self.assertEqual(enriched["count"], original["count"])
        self.assertEqual(enriched["busy_slots"], [{**original["busy_slots"][0], "title": title}])
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/calendar/v3/calendars/primary/events")
        for key, value in {
            "singleEvents": "true",
            "showDeleted": "false",
            "maxResults": "2500",
            "timeMin": "2026-11-06T00:00:00+00:00",
            "timeMax": "2026-11-07T00:00:00+00:00",
        }.items():
            self.assertEqual(request.url.params[key], value)
        self.assertNotIn("timeZone", request.url.params)
        self.assertNotIn("description", request.url.params["fields"])
        self.assertNotIn("attendees", request.url.params["fields"])
        self.assertEqual(request.headers["Authorization"], "Bearer dummy-access")

    def test_overlapping_and_adjacent_events_keep_individual_titles(self) -> None:
        self.pages[0]["items"] = [
            timed_event("2026-11-06T09:00:00Z", "2026-11-06T10:00:00Z", "First"),
            timed_event("2026-11-06T09:30:00Z", "2026-11-06T11:00:00Z", "Second"),
            timed_event("2026-11-06T11:00:00Z", "2026-11-06T12:00:00Z", "Third"),
        ]
        original, result = self.read(), self.read(include_busy_titles=True)
        self.assertEqual(
            [slot["title"] for slot in result["busy_slots"]], ["First", "Second", "Third"]
        )
        self.assertEqual(result["busy_slots"][1]["start"], "2026-11-06T09:30:00+00:00")
        self.assertEqual(result["available_slots"], original["available_slots"])

    def test_unlabelled_busy_time_stays_busy_with_null_title(self) -> None:
        self.pages[0]["items"] = [
            timed_event("2026-11-06T10:00:00Z", "2026-11-06T11:00:00Z", "Visible")
        ]
        result = self.read(include_busy_titles=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T10:00:00+00:00",
                    "title": None,
                },
                {
                    "start": "2026-11-06T10:00:00+00:00",
                    "end": "2026-11-06T11:00:00+00:00",
                    "title": "Visible",
                },
                {
                    "start": "2026-11-06T11:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": None,
                },
            ],
        )

    def test_private_event_without_summary_has_null_title(self) -> None:
        self.pages[0]["items"][0].pop("summary")
        self.assertIsNone(self.read(include_busy_titles=True)["busy_slots"][0]["title"])

    def test_free_cancelled_and_out_of_window_events_cannot_label_busy_time(self) -> None:
        self.pages[0]["items"] = [
            timed_event(
                "2026-11-06T09:00:00Z",
                "2026-11-06T12:00:00Z",
                "Free event",
                transparency="transparent",
            ),
            {"status": "cancelled", "summary": "Deleted event"},
            timed_event("2026-11-07T09:00:00Z", "2026-11-07T12:00:00Z", "Outside window"),
        ]
        result = self.read(include_busy_titles=True)
        self.assertEqual(len(result["busy_slots"]), 1)
        self.assertIsNone(result["busy_slots"][0]["title"])

    def test_all_day_event_uses_calendar_zone_with_exclusive_end(self) -> None:
        self.busy = [{"start": "2026-11-06T05:00:00Z", "end": "2026-11-07T05:00:00Z"}]
        self.pages = [
            {
                "timeZone": "America/New_York",
                "items": [
                    {
                        "start": {"date": "2026-11-06"},
                        "end": {"date": "2026-11-07"},
                        "summary": "Holiday",
                    }
                ],
            }
        ]
        result = self.read(include_busy_titles=True, time_zone="Europe/Berlin")
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T06:00:00+01:00",
                    "end": "2026-11-07T01:00:00+01:00",
                    "title": "Holiday",
                }
            ],
        )

    def test_recurring_instances_page_through_empty_and_nonempty_pages(self) -> None:
        self.pages = [
            {"timeZone": "UTC", "items": [], "nextPageToken": "page-2"},
            {
                "timeZone": "UTC",
                "items": [
                    timed_event("2026-11-06T09:00:00Z", "2026-11-06T10:00:00Z", "Daily standup")
                ],
                "nextPageToken": "page-3",
            },
            {
                "timeZone": "UTC",
                "items": [
                    timed_event("2026-11-06T10:00:00Z", "2026-11-06T12:00:00Z", "Daily standup")
                ],
            },
        ]
        result = self.read(include_busy_titles=True)
        self.assertEqual(
            [slot["title"] for slot in result["busy_slots"]], ["Daily standup", "Daily standup"]
        )
        gets = [request for request in self.requests if request.method == "GET"]
        self.assertEqual(len(gets), 3)
        self.assertEqual(gets[1].url.params["pageToken"], "page-2")
        self.assertEqual(gets[2].url.params["pageToken"], "page-3")

    def test_bad_pagination_and_invalid_events_fail_without_partial_output(self) -> None:
        for pages in (
            [{"timeZone": "UTC", "items": [], "nextPageToken": "loop"}],
            [{"timeZone": "UTC", "items": "bad"}],
            [{"timeZone": "UTC", "items": [{"summary": "No times"}]}],
        ):
            with self.subTest(pages=pages):
                self.pages, self.page_index = pages, 0
                with self.assertRaises(HTTPException):
                    self.read(include_busy_titles=True)

    def test_events_denial_fails_only_when_titles_are_enabled(self) -> None:
        self.events_status = 403
        self.assertEqual(self.read()["status"], "success")
        with self.assertRaises(HTTPException) as caught:
            self.read(include_busy_titles=True)
        self.assertEqual(caught.exception.status_code, 403)

    def test_no_busy_time_needs_no_event_lookup_even_when_enabled(self) -> None:
        self.busy = []
        self.assertEqual(self.read(include_busy_titles=True)["busy_slots"], [])
        self.assertEqual(len(self.requests), 1)

    def test_titles_cannot_create_busy_time_outside_freebusy(self) -> None:
        self.pages[0]["items"] = [
            timed_event("2026-11-05T23:00:00Z", "2026-11-07T01:00:00Z", "Long event")
        ]
        result = self.read(include_busy_titles=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": "Long event",
                }
            ],
        )

    def test_event_explicit_zone_interprets_local_datetime_without_offset(self) -> None:
        self.pages = [
            {
                "timeZone": "America/New_York",
                "items": [
                    {
                        "summary": "Berlin meeting",
                        "start": {"dateTime": "2026-11-06T10:00:00", "timeZone": "Europe/Berlin"},
                        "end": {"dateTime": "2026-11-06T13:00:00", "timeZone": "Europe/Berlin"},
                    }
                ],
            }
        ]
        result = self.read(include_busy_titles=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": "Berlin meeting",
                }
            ],
        )

    def test_busy_slots_stay_chronological_across_repeated_dst_hour(self) -> None:
        self.busy = [{"start": "2026-10-25T00:00:00Z", "end": "2026-10-25T02:00:00Z"}]
        self.pages = [
            {
                "timeZone": "Europe/Berlin",
                "items": [
                    timed_event("2026-10-25T00:30:00Z", "2026-10-25T00:45:00Z", "Before rollback"),
                    timed_event("2026-10-25T01:00:00Z", "2026-10-25T01:30:00Z", "After rollback"),
                ],
            }
        ]
        result = self.service.read_availability(
            start="2026-10-25T00:00:00Z",
            end="2026-10-25T02:00:00Z",
            time_zone="Europe/Berlin",
            include_busy_titles=True,
        )
        named = [slot for slot in result["busy_slots"] if slot["title"] is not None]
        self.assertEqual([slot["title"] for slot in named], ["Before rollback", "After rollback"])
        self.assertEqual(named[0]["start"], "2026-10-25T02:30:00+02:00")
        self.assertEqual(named[1]["start"], "2026-10-25T02:00:00+01:00")
