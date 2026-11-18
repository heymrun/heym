"""Exchange Server sending and calendar: messages, free time, free/busy and invitations."""

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from exchangelib import errors as ews
from exchangelib.items import SEND_TO_ALL_AND_SAVE_COPY, SEND_TO_NONE
from fastapi import HTTPException

from app.services.email_compose import EmailAttachment, EmailFields
from app.services.exchange_server import calendar as ews_calendar
from app.services.exchange_server import send as ews_send
from app.services.exchange_server.calendar import ExchangeCalendarService, busy_event
from app.services.outlook_service import OutlookApiError

CONFIG = {
    "auth_mode": "ews",
    "ews_email": "ada@heym.run",
    "ews_username": "HEYM\\ada",
    "ews_password": "pw",
    "ews_server": "mail.heym.run",
}
UTC = timezone.utc


def _fields(**extra: str) -> EmailFields:
    values = {
        "to": '"Lovelace, Ada" <ada@x.com>, bob@x.com',
        "cc": "",
        "bcc": "",
        "subject": "Hello",
        "body": "Plain text",
        "attachments": "",
    }
    values.update(extra)
    return EmailFields(**values)


class SendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = SimpleNamespace(sent="sent-folder")
        patcher = patch.object(ews_send, "Message")
        self.message = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_message_keeps_names_and_goes_to_sent_items(self) -> None:
        ews_send.build_message(self.account, _fields(), "", [])

        kwargs = self.message.call_args.kwargs
        self.assertEqual(kwargs["folder"], "sent-folder")
        self.assertEqual(kwargs["subject"], "Hello")
        self.assertEqual(
            [(box.name, box.email_address) for box in kwargs["to_recipients"]],
            [("Lovelace, Ada", "ada@x.com"), (None, "bob@x.com")],
        )
        self.assertIsNone(kwargs["cc_recipients"])
        self.assertIsNone(kwargs["bcc_recipients"])
        self.assertEqual(type(kwargs["body"]).__name__, "Body")

    def test_html_body_from_address_and_attachments(self) -> None:
        attachment = EmailAttachment("a.pdf", "application/pdf", b"%PDF")
        ews_send.build_message(
            self.account,
            _fields(body="<p>Hi</p>", cc="c@x.com", bcc="d@x.com"),
            "team@heym.run",
            [attachment],
        )
        kwargs = self.message.call_args.kwargs
        self.assertEqual(type(kwargs["body"]).__name__, "HTMLBody")
        self.assertEqual(kwargs["cc_recipients"][0].email_address, "c@x.com")
        self.assertEqual(kwargs["bcc_recipients"][0].email_address, "d@x.com")
        built = self.message.return_value
        self.assertEqual(built.author.email_address, "team@heym.run")
        file = built.attach.call_args.args[0]
        self.assertEqual(
            (file.name, file.content, file.content_type), ("a.pdf", b"%PDF", "application/pdf")
        )

    def test_send_message_sends_and_saves_and_maps_errors(self) -> None:
        with patch.object(ews_send, "ews_account", return_value=self.account):
            ews_send.send_message(CONFIG, _fields(), "", [])
        self.message.return_value.send_and_save.assert_called_once_with()

        self.message.return_value.send_and_save.side_effect = ews.ErrorSendAsDenied("no")
        with (
            patch.object(ews_send, "ews_account", return_value=self.account),
            self.assertRaises(OutlookApiError) as caught,
        ):
            ews_send.send_message(CONFIG, _fields(), "boss@heym.run", [])
        self.assertEqual(caught.exception.status_code, 403)


def _event(start: object, end: object, status: str = "Busy", **extra: object) -> SimpleNamespace:
    values = {
        "start": start,
        "end": end,
        "legacy_free_busy_status": status,
        "is_cancelled": False,
        "is_all_day": False,
        "subject": "Standup",
        "required_attendees": [SimpleNamespace(mailbox=SimpleNamespace(email_address="a@x.com"))],
        "optional_attendees": None,
    }
    values.update(extra)
    return SimpleNamespace(**values)


class BusyEventTests(unittest.TestCase):
    def test_only_blocking_statuses_count(self) -> None:
        zone = ZoneInfo("UTC")
        start, end = datetime(2026, 12, 1, 9, tzinfo=UTC), datetime(2026, 12, 1, 10, tzinfo=UTC)
        for status, blocks in (
            ("Busy", True),
            ("Tentative", True),
            ("OOF", True),
            ("NoData", True),
            ("Free", False),
            ("WorkingElsewhere", False),
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    busy_event(_event(start, end, status), zone, details=False) is not None, blocks
                )
        self.assertIsNone(busy_event(_event(start, end, is_cancelled=True), zone, details=False))

    def test_real_ews_datetimes_and_dates_are_read(self) -> None:
        from exchangelib import EWSDate, EWSDateTime, EWSTimeZone

        utc = EWSTimeZone("UTC")
        timed = _event(
            EWSDateTime(2026, 12, 1, 9, tzinfo=utc), EWSDateTime(2026, 12, 1, 10, tzinfo=utc)
        )
        event = busy_event(timed, ZoneInfo("Europe/Istanbul"), details=False)
        self.assertEqual(
            (event.start, event.end),
            (datetime(2026, 12, 1, 9, tzinfo=UTC), datetime(2026, 12, 1, 10, tzinfo=UTC)),
        )
        self.assertIs(type(event.start), datetime)

        all_day = _event(EWSDate(2026, 12, 1), EWSDate(2026, 12, 2), is_all_day=True)
        event = busy_event(all_day, ZoneInfo("UTC"), details=False)
        self.assertEqual(event.start, datetime(2026, 12, 1, tzinfo=UTC))

    def test_all_day_events_hold_their_date_in_the_readers_zone(self) -> None:
        zone = ZoneInfo("Europe/Istanbul")
        for start, end in (
            (date(2026, 12, 1), date(2026, 12, 2)),
            (datetime(2026, 12, 1, tzinfo=UTC), datetime(2026, 12, 2, tzinfo=UTC)),
        ):
            with self.subTest(start=start):
                event = busy_event(_event(start, end, is_all_day=True), zone, details=True)
                self.assertEqual(event.start, datetime(2026, 11, 30, 21, tzinfo=UTC))
                self.assertEqual(event.title, "Standup")
                self.assertEqual(event.attendees, ["a@x.com"])


class CalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = MagicMock()
        self.account.calendar = SimpleNamespace(
            id="cal", name="Calendar", folder_class="IPF.Appointment", view=MagicMock()
        )
        team = SimpleNamespace(id="team-cal", name="Team", folder_class="IPF.Appointment")
        inbox = SimpleNamespace(id="inbox", name="Inbox", folder_class="IPF.Note")
        self.account.msg_folder_root.walk.return_value = [inbox, team, self.account.calendar]
        self.service = ExchangeCalendarService(CONFIG)
        self.service._account = self.account

    def _view(self, items: list[object]) -> None:
        query = MagicMock()
        query.only.return_value.__getitem__.side_effect = lambda window: items[window]
        self.account.calendar.view.return_value = query

    def test_free_time_is_read_from_the_calendar_view(self) -> None:
        self._view(
            [_event(datetime(2026, 12, 1, 9, tzinfo=UTC), datetime(2026, 12, 1, 10, tzinfo=UTC))]
        )
        result = self.service.read_availability(
            "primary", "2026-12-01T08:00:00Z", "2026-12-01T12:00:00Z", "UTC"
        )
        self.assertEqual(
            result["busy_slots"],
            [{"start": "2026-12-01T09:00:00+00:00", "end": "2026-12-01T10:00:00+00:00"}],
        )
        self.assertEqual(result["count"], 2)
        view = self.account.calendar.view.call_args.kwargs
        self.assertEqual(view["start"], datetime(2026, 12, 1, 8, tzinfo=UTC))

    def test_a_colleague_is_read_through_free_busy(self) -> None:
        free_busy = SimpleNamespace(
            calendar_events=[
                SimpleNamespace(
                    start=datetime(2026, 12, 1, 9, tzinfo=UTC),
                    end=datetime(2026, 12, 1, 9, 30, tzinfo=UTC),
                    busy_type="Busy",
                    details=SimpleNamespace(subject="1:1", is_private=False),
                )
            ]
        )
        self.account.protocol.get_free_busy_info.return_value = iter([free_busy])
        result = self.service.read_availability(
            "colleague@heym.run", "2026-12-01T08:00:00Z", "2026-12-01T10:00:00Z", "UTC"
        )
        call = self.account.protocol.get_free_busy_info.call_args.kwargs
        self.assertEqual(call["accounts"], [("colleague@heym.run", "Required", False)])
        self.assertEqual(len(result["busy_slots"]), 1)

        self.account.protocol.get_free_busy_info.return_value = iter([ews.ErrorAccessDenied("x")])
        with self.assertRaises(HTTPException) as caught:
            self.service.read_availability("colleague@heym.run", "2026-12-01", "2026-12-02", "UTC")
        self.assertEqual(caught.exception.status_code, 403)

    def test_calendars_resolve_by_name_and_saving_elsewhere_is_refused(self) -> None:
        folder, schedule = self.service.resolve_calendar("team", allow_schedule=False)
        self.assertEqual((folder.id, schedule), ("team-cal", ""))
        self.assertEqual(
            self.service.resolve_calendar("ada@heym.run", allow_schedule=False)[0].id, "cal"
        )
        for value, status in (("someone@x.com", 400), ("Missing", 404)):
            with self.subTest(value=value), self.assertRaises(HTTPException) as caught:
                self.service.resolve_calendar(value, allow_schedule=False)
            self.assertEqual(caught.exception.status_code, status)

    def test_create_sends_invitations_only_with_attendees_and_reports_no_teams(self) -> None:
        with patch.object(ews_calendar, "CalendarItem") as item_class:
            item_class.return_value = MagicMock(
                id="new", web_client_read_form_query_string="https://owa"
            )
            result = self.service.save_event(
                "create",
                "primary",
                "",
                title="Review",
                start="2026-12-01T09:00:00Z",
                end="2026-12-01T10:00:00Z",
                attendees="a@x.com, b@x.com",
            )
            kwargs = item_class.call_args.kwargs
            item_class.return_value.save.assert_called_once_with(
                send_meeting_invitations=SEND_TO_ALL_AND_SAVE_COPY
            )
            self.assertEqual(kwargs["required_attendees"], ["a@x.com", "b@x.com"])
            self.assertEqual(kwargs["folder"].id, "cal")
            self.assertEqual(
                (result["event_id"], result["teams_status"], result["teams_url"]),
                ("new", "unavailable", ""),
            )

            item_class.return_value.save.reset_mock()
            self.service.save_event(
                "create",
                "primary",
                "",
                title="Focus",
                start="2026-12-01T11:00:00Z",
                end="2026-12-01T12:00:00Z",
                teams_meeting=False,
            )
            item_class.return_value.save.assert_called_once_with(
                send_meeting_invitations=SEND_TO_NONE
            )

    def test_update_and_delete_work_on_the_fetched_event(self) -> None:
        event = MagicMock(id="ev1", required_attendees=["a@x.com"], optional_attendees=None)
        self.account.fetch.return_value = [event]
        result = self.service.save_event("update", "primary", "ev1", title="Moved")
        self.assertEqual(event.subject, "Moved")
        event.save.assert_called_once_with(
            update_fields=["subject"], send_meeting_invitations=SEND_TO_ALL_AND_SAVE_COPY
        )
        self.assertEqual(result["teams_status"], "off")

        self.account.fetch.return_value = [event]
        self.service.delete_event("ev1")
        event.delete.assert_called_once_with(send_meeting_cancellations=SEND_TO_ALL_AND_SAVE_COPY)

    def test_exchange_failures_become_node_errors(self) -> None:
        self.account.fetch.return_value = [ews.ErrorItemNotFound("gone")]
        with self.assertRaises(HTTPException) as caught:
            self.service.delete_event("ev1")
        self.assertEqual(caught.exception.status_code, 404)

        service = ExchangeCalendarService(CONFIG)
        with (
            patch.object(ews_calendar, "ews_account", side_effect=ews.UnauthorizedError("no")),
            self.assertRaises(HTTPException) as caught,
        ):
            service.read_availability("primary", "2026-12-01", "2026-12-02", "UTC")
        self.assertEqual(caught.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
