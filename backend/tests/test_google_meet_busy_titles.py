"""Opt-in busy titles preserve availability and Google's detail visibility."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException

from app.services.google_meet_busy_titles import can_see_event_details
from app.services.google_meet_service import GoogleMeetService


def timed_event(start: str, end: str, title: str | None = "Team meeting", **extra: object) -> dict:
    """Build an occurrence from the documented Calendar Events list contract."""
    event = {"start": {"dateTime": start}, "end": {"dateTime": end}, **extra}
    if title is not None:
        event["summary"] = title
    return event


class TestCanSeeEventDetails(unittest.TestCase):
    def test_owner_and_writer_allow_all_documented_visibilities(self) -> None:
        for role in ("owner", "writer", "Owner", "WRITER"):
            for vis in ("default", "public", "private", "confidential"):
                with self.subTest(role=role, visibility=vis):
                    self.assertTrue(can_see_event_details(role, vis))
            # Missing visibility means default
            with self.subTest(role=role, visibility=None):
                self.assertTrue(can_see_event_details(role, None))
            # Unknown visibility fails closed
            for bad_vis in ("unknown", "restricted", 123, ""):
                with self.subTest(role=role, visibility=bad_vis):
                    self.assertFalse(can_see_event_details(role, bad_vis))

    def test_reader_and_writer_without_private_access(self) -> None:
        for role in (
            "reader",
            "writerWithoutPrivateAccess",
            "READER",
            "writerwithoutprivateaccess",
        ):
            # Explicitly allow only public and default
            self.assertTrue(can_see_event_details(role, "public"))
            self.assertTrue(can_see_event_details(role, "default"))
            self.assertTrue(can_see_event_details(role, None))  # missing means default
            # Private and confidential are disallowed
            self.assertFalse(can_see_event_details(role, "private"))
            self.assertFalse(can_see_event_details(role, "confidential"))
            # Unknown visibility fails closed
            self.assertFalse(can_see_event_details(role, "unknown"))

    def test_free_busy_reader_allows_only_public(self) -> None:
        for role in ("freeBusyReader", "freebusyreader", "FREEBUSYREADER"):
            self.assertTrue(can_see_event_details(role, "public"))
            self.assertFalse(can_see_event_details(role, "default"))
            self.assertFalse(can_see_event_details(role, None))  # missing means default
            self.assertFalse(can_see_event_details(role, "private"))
            self.assertFalse(can_see_event_details(role, "confidential"))
            self.assertFalse(can_see_event_details(role, "unknown"))

    def test_missing_and_unknown_roles_fail_closed(self) -> None:
        for role in (None, "", "unknown", "admin", 123, []):
            for vis in ("public", "default", "private", "confidential", None, "unknown"):
                with self.subTest(role=role, visibility=vis):
                    self.assertFalse(can_see_event_details(role, vis))


class TestGoogleMeetBusyTitles(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T12:00:00Z"}]
        self.pages: list[dict] = [
            {
                "accessRole": "owner",
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
        for kwargs in ({}, {"include_busy_details": False}, {"include_busy_titles": False}):
            with self.subTest(kwargs=kwargs):
                result = self.read(**kwargs)
                self.assertEqual(
                    result["busy_slots"],
                    [{"start": "2026-11-06T09:00:00+00:00", "end": "2026-11-06T12:00:00+00:00"}],
                )
                self.assertNotIn("Team meeting", str(result))
                self.assertNotIn("attendees", result["busy_slots"][0])
        self.assertTrue(all(request.method == "POST" for request in self.requests))

    def test_enabled_returns_actual_title_and_preserves_available_slots(self) -> None:
        title = 'Design review: "release"\nFollow-up'
        self.pages[0]["items"][0]["summary"] = title
        original, enriched = self.read(), self.read(include_busy_details=True)
        self.assertEqual(enriched["available_slots"], original["available_slots"])
        self.assertEqual(enriched["count"], original["count"])
        self.assertEqual(
            enriched["busy_slots"],
            [{**original["busy_slots"][0], "title": title, "attendees": []}],
        )
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
        self.assertIn("accessRole", request.url.params["fields"])
        self.assertIn("visibility", request.url.params["fields"])
        self.assertIn("attendeesOmitted", request.url.params["fields"])
        self.assertIn("attendees(email,resource)", request.url.params["fields"])
        self.assertEqual(request.headers["Authorization"], "Bearer dummy-access")

    def test_attendee_emails_are_returned_and_resources_excluded(self) -> None:
        self.pages[0]["items"][0]["attendees"] = [
            {"email": "alice@example.com"},
            {"email": "conf-room-1@example.com", "resource": True},
            {"email": "bob@example.com", "resource": False},
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"][0]["attendees"],
            ["alice@example.com", "bob@example.com"],
        )

    def test_no_guests_and_only_resources_return_empty_array(self) -> None:
        for attendees_val in (
            [],
            [{"email": "room@example.com", "resource": True}],
        ):
            with self.subTest(attendees=attendees_val):
                self.pages[0]["items"][0]["attendees"] = attendees_val
                result = self.read(include_busy_details=True)
                self.assertEqual(result["busy_slots"][0]["attendees"], [])

    def test_overlapping_and_adjacent_events_keep_individual_titles(self) -> None:
        self.pages[0]["items"] = [
            timed_event(
                "2026-11-06T09:00:00Z",
                "2026-11-06T10:00:00Z",
                "First",
                attendees=[{"email": "first@example.com"}],
            ),
            timed_event(
                "2026-11-06T09:30:00Z",
                "2026-11-06T11:00:00Z",
                "Second",
                attendees=[{"email": "second@example.com"}],
            ),
            timed_event(
                "2026-11-06T11:00:00Z",
                "2026-11-06T12:00:00Z",
                "Third",
            ),
        ]
        original, result = self.read(), self.read(include_busy_details=True)
        self.assertEqual(
            [slot["title"] for slot in result["busy_slots"]], ["First", "Second", "Third"]
        )
        self.assertEqual(
            [slot["attendees"] for slot in result["busy_slots"]],
            [["first@example.com"], ["second@example.com"], []],
        )
        self.assertEqual(result["busy_slots"][1]["start"], "2026-11-06T09:30:00+00:00")
        self.assertEqual(result["available_slots"], original["available_slots"])

    def test_unlabelled_busy_time_stays_busy_with_null_title(self) -> None:
        self.pages[0]["items"] = [
            timed_event("2026-11-06T10:00:00Z", "2026-11-06T11:00:00Z", "Visible")
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T10:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
                {
                    "start": "2026-11-06T10:00:00+00:00",
                    "end": "2026-11-06T11:00:00+00:00",
                    "title": "Visible",
                    "attendees": [],
                },
                {
                    "start": "2026-11-06T11:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
            ],
        )

    def test_private_event_without_summary_has_null_title(self) -> None:
        self.pages[0]["items"][0].pop("summary")
        self.assertIsNone(self.read(include_busy_titles=True)["busy_slots"][0]["title"])

    def test_free_busy_reader_can_see_public_event_details(self) -> None:
        self.pages[0]["accessRole"] = "freeBusyReader"
        self.pages[0]["items"] = [
            timed_event(
                "2026-11-06T09:00:00Z",
                "2026-11-06T12:00:00Z",
                title="Visible Public Event",
                visibility="public",
                attendees=[{"email": "public-guest@example.com"}],
            )
        ]
        result = self.read(include_busy_details=True)
        slot = result["busy_slots"][0]
        self.assertEqual(slot["title"], "Visible Public Event")
        self.assertEqual(slot["attendees"], ["public-guest@example.com"])

    def test_free_busy_reader_cannot_see_default_private_or_confidential_events(self) -> None:
        self.pages[0]["accessRole"] = "freeBusyReader"
        for visibility in ("default", "private", "confidential", None):
            with self.subTest(visibility=visibility):
                event_kwargs = {"visibility": visibility} if visibility else {}
                self.pages[0]["items"] = [
                    timed_event(
                        "2026-11-06T09:00:00Z",
                        "2026-11-06T12:00:00Z",
                        title="Hidden Event Details",
                        attendees=[{"email": "hidden-guest@example.com"}],
                        **event_kwargs,
                    )
                ]
                result = self.read(include_busy_details=True)
                slot = result["busy_slots"][0]
                self.assertIsNone(slot["title"])
                self.assertIsNone(slot["attendees"])

    def test_reader_can_see_public_and_default_event_details(self) -> None:
        self.pages[0]["accessRole"] = "reader"
        for visibility in ("public", "default", None):
            with self.subTest(visibility=visibility):
                event_kwargs = {"visibility": visibility} if visibility else {}
                self.pages[0]["items"] = [
                    timed_event(
                        "2026-11-06T09:00:00Z",
                        "2026-11-06T12:00:00Z",
                        title="Public Meeting",
                        attendees=[{"email": "guest@example.com"}],
                        **event_kwargs,
                    )
                ]
                result = self.read(include_busy_details=True)
                slot = result["busy_slots"][0]
                self.assertEqual(slot["title"], "Public Meeting")
                self.assertEqual(slot["attendees"], ["guest@example.com"])

    def test_writer_without_private_access_cannot_see_private_event_details(self) -> None:
        self.pages[0]["accessRole"] = "writerWithoutPrivateAccess"
        for visibility in ("private", "confidential"):
            with self.subTest(visibility=visibility):
                self.pages[0]["items"] = [
                    timed_event(
                        "2026-11-06T09:00:00Z",
                        "2026-11-06T12:00:00Z",
                        title="Private Strategy",
                        visibility=visibility,
                        attendees=[{"email": "exec@example.com"}],
                    )
                ]
                result = self.read(include_busy_details=True)
                slot = result["busy_slots"][0]
                self.assertIsNone(slot["title"])
                self.assertIsNone(slot["attendees"])

    def test_owner_and_writer_can_see_private_event_details(self) -> None:
        for role in ("owner", "writer", "Owner", "WRITER"):
            for visibility in ("private", "confidential"):
                with self.subTest(role=role, visibility=visibility):
                    self.pages[0]["accessRole"] = role
                    self.pages[0]["items"] = [
                        timed_event(
                            "2026-11-06T09:00:00Z",
                            "2026-11-06T12:00:00Z",
                            title="Private Doctor Appointment",
                            visibility=visibility,
                            attendees=[{"email": "doctor@example.com"}],
                        )
                    ]
                    result = self.read(include_busy_details=True)
                    slot = result["busy_slots"][0]
                    self.assertEqual(slot["title"], "Private Doctor Appointment")
                    self.assertEqual(slot["attendees"], ["doctor@example.com"])

    def test_missing_or_unknown_access_roles_fail_closed_for_all_events(self) -> None:
        for access_role in (None, "unknownRole", "guest", 123, ""):
            for visibility in ("public", "default", "private", "confidential", None):
                with self.subTest(access_role=access_role, visibility=visibility):
                    if access_role is None:
                        self.pages[0].pop("accessRole", None)
                    else:
                        self.pages[0]["accessRole"] = access_role
                    event_kwargs = {"visibility": visibility} if visibility else {}
                    self.pages[0]["items"] = [
                        timed_event(
                            "2026-11-06T09:00:00Z",
                            "2026-11-06T12:00:00Z",
                            title="Important Event",
                            attendees=[{"email": "guest@example.com"}],
                            **event_kwargs,
                        )
                    ]
                    result = self.read(include_busy_details=True)
                    slot = result["busy_slots"][0]
                    self.assertIsNone(slot["title"])
                    self.assertIsNone(slot["attendees"])

    def test_visible_event_with_no_guests_returns_empty_attendees_list(self) -> None:
        for access_role in ("reader", "owner"):
            for visibility in (None, "public", "default"):
                with self.subTest(access_role=access_role, visibility=visibility):
                    self.pages[0]["accessRole"] = access_role
                    event_kwargs = {"visibility": visibility} if visibility else {}
                    self.pages[0]["items"] = [
                        timed_event(
                            "2026-11-06T09:00:00Z",
                            "2026-11-06T12:00:00Z",
                            title="Visible Meeting",
                            **event_kwargs,
                        )
                    ]
                    result = self.read(include_busy_details=True)
                    slot = result["busy_slots"][0]
                    self.assertEqual(slot["title"], "Visible Meeting")
                    self.assertEqual(slot["attendees"], [])

    def test_attendees_omitted_returns_null_attendees_and_preserves_title(self) -> None:
        # When attendeesOmitted is True and partial attendee list is returned in response:
        self.pages[0]["items"] = [
            timed_event(
                "2026-11-06T09:00:00Z",
                "2026-11-06T12:00:00Z",
                title="Company All-Hands",
                attendeesOmitted=True,
                attendees=[{"email": "partial-guest@example.com"}],
            )
        ]
        result = self.read(include_busy_details=True)
        slot = result["busy_slots"][0]
        self.assertEqual(slot["title"], "Company All-Hands")
        self.assertIsNone(slot["attendees"])

        # When attendeesOmitted is True and no attendees field is present:
        self.pages[0]["items"] = [
            timed_event(
                "2026-11-06T09:00:00Z",
                "2026-11-06T12:00:00Z",
                title="Large Conference",
                attendeesOmitted=True,
            )
        ]
        result = self.read(include_busy_details=True)
        slot = result["busy_slots"][0]
        self.assertEqual(slot["title"], "Large Conference")
        self.assertIsNone(slot["attendees"])

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
                "accessRole": "owner",
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
                    "attendees": [],
                }
            ],
        )

    def test_recurring_instances_page_through_empty_and_nonempty_pages(self) -> None:
        self.pages = [
            {"accessRole": "owner", "timeZone": "UTC", "items": [], "nextPageToken": "page-2"},
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event("2026-11-06T09:00:00Z", "2026-11-06T10:00:00Z", "Daily standup")
                ],
                "nextPageToken": "page-3",
            },
            {
                "accessRole": "owner",
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
                    "attendees": [],
                }
            ],
        )

    def test_event_explicit_zone_interprets_local_datetime_without_offset(self) -> None:
        self.pages = [
            {
                "accessRole": "owner",
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
                    "attendees": [],
                }
            ],
        )

    def test_busy_slots_stay_chronological_across_repeated_dst_hour(self) -> None:
        self.busy = [{"start": "2026-10-25T00:00:00Z", "end": "2026-10-25T02:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
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

    def test_freebusy_09_to_12_with_event_10_to_11(self) -> None:
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T12:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event(
                        "2026-11-06T10:00:00Z",
                        "2026-11-06T11:00:00Z",
                        "Team Sync",
                        attendees=[{"email": "colleague@example.com"}],
                    )
                ],
            }
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T10:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
                {
                    "start": "2026-11-06T10:00:00+00:00",
                    "end": "2026-11-06T11:00:00+00:00",
                    "title": "Team Sync",
                    "attendees": ["colleague@example.com"],
                },
                {
                    "start": "2026-11-06T11:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
            ],
        )

    def test_multiple_events_inside_one_freebusy_interval(self) -> None:
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T13:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event(
                        "2026-11-06T09:30:00Z",
                        "2026-11-06T10:30:00Z",
                        "First Session",
                        attendees=[{"email": "first@example.com"}],
                    ),
                    timed_event(
                        "2026-11-06T11:00:00Z",
                        "2026-11-06T12:00:00Z",
                        "Second Session",
                        attendees=[{"email": "second@example.com"}],
                    ),
                ],
            }
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T09:30:00+00:00",
                    "title": None,
                    "attendees": None,
                },
                {
                    "start": "2026-11-06T09:30:00+00:00",
                    "end": "2026-11-06T10:30:00+00:00",
                    "title": "First Session",
                    "attendees": ["first@example.com"],
                },
                {
                    "start": "2026-11-06T10:30:00+00:00",
                    "end": "2026-11-06T11:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
                {
                    "start": "2026-11-06T11:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": "Second Session",
                    "attendees": ["second@example.com"],
                },
                {
                    "start": "2026-11-06T12:00:00+00:00",
                    "end": "2026-11-06T13:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
            ],
        )

    def test_overlapping_events_inside_one_freebusy_interval_preserved_separately(self) -> None:
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T12:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event(
                        "2026-11-06T10:00:00Z",
                        "2026-11-06T11:30:00Z",
                        "Long Workshop",
                        attendees=[{"email": "workshop@example.com"}],
                    ),
                    timed_event(
                        "2026-11-06T10:30:00Z",
                        "2026-11-06T11:00:00Z",
                        "Short Checkin",
                        attendees=[{"email": "checkin@example.com"}],
                    ),
                ],
            }
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T10:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
                {
                    "start": "2026-11-06T10:00:00+00:00",
                    "end": "2026-11-06T11:30:00+00:00",
                    "title": "Long Workshop",
                    "attendees": ["workshop@example.com"],
                },
                {
                    "start": "2026-11-06T10:30:00+00:00",
                    "end": "2026-11-06T11:00:00+00:00",
                    "title": "Short Checkin",
                    "attendees": ["checkin@example.com"],
                },
                {
                    "start": "2026-11-06T11:30:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": None,
                    "attendees": None,
                },
            ],
        )

    def test_event_extending_beyond_requested_window_is_clipped(self) -> None:
        self.busy = [{"start": "2026-11-06T22:00:00Z", "end": "2026-11-07T00:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event(
                        "2026-11-06T22:00:00Z",
                        "2026-11-07T04:00:00Z",
                        "Late Night Hackathon",
                        attendees=[{"email": "hacker@example.com"}],
                    )
                ],
            }
        ]
        result = self.service.read_availability(
            start="2026-11-06T00:00:00Z",
            end="2026-11-07T00:00:00Z",
            time_zone="UTC",
            include_busy_details=True,
        )
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T22:00:00+00:00",
                    "end": "2026-11-07T00:00:00+00:00",
                    "title": "Late Night Hackathon",
                    "attendees": ["hacker@example.com"],
                }
            ],
        )

    def test_event_not_overlapping_freebusy_is_not_returned(self) -> None:
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T10:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event(
                        "2026-11-06T14:00:00Z",
                        "2026-11-06T15:00:00Z",
                        "Non-Blocking Coffee",
                        attendees=[{"email": "friend@example.com"}],
                    )
                ],
            }
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T10:00:00+00:00",
                    "title": None,
                    "attendees": None,
                }
            ],
        )

    def test_empty_freebusy_means_no_busy_slots_even_if_events_list_has_event(self) -> None:
        self.busy = []
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [
                    timed_event(
                        "2026-11-06T10:00:00Z",
                        "2026-11-06T11:00:00Z",
                        "Phantom Event",
                        attendees=[{"email": "phantom@example.com"}],
                    )
                ],
            }
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(result["busy_slots"], [])
        self.assertEqual(result["count"], 1)

    def test_missing_event_details_never_cause_freebusy_busy_time_to_vanish(self) -> None:
        self.busy = [{"start": "2026-11-06T09:00:00Z", "end": "2026-11-06T12:00:00Z"}]
        self.pages = [
            {
                "accessRole": "owner",
                "timeZone": "UTC",
                "items": [],
            }
        ]
        result = self.read(include_busy_details=True)
        self.assertEqual(
            result["busy_slots"],
            [
                {
                    "start": "2026-11-06T09:00:00+00:00",
                    "end": "2026-11-06T12:00:00+00:00",
                    "title": None,
                    "attendees": None,
                }
            ],
        )

    def test_unknown_visibility_values_fail_closed_for_all_roles(self) -> None:
        for role in (
            "owner",
            "writer",
            "reader",
            "writerWithoutPrivateAccess",
            "freeBusyReader",
        ):
            with self.subTest(role=role):
                self.pages = [
                    {
                        "accessRole": role,
                        "timeZone": "UTC",
                        "items": [
                            timed_event(
                                "2026-11-06T09:00:00Z",
                                "2026-11-06T12:00:00Z",
                                title="Custom Visibility Meeting",
                                visibility="customUnknownVisibility",
                                attendees=[{"email": "user@example.com"}],
                            )
                        ],
                    }
                ]
                result = self.read(include_busy_details=True)
                slot = result["busy_slots"][0]
                self.assertIsNone(slot["title"])
                self.assertIsNone(slot["attendees"])
