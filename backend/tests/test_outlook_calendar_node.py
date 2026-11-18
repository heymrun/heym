"""Outlook Calendar node dispatch, dynamic booking fields and accessible credential checks."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.db.models import CredentialType
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.outlook_calendar_node import execute

_MODULE = "app.services.node_execution.nodes.outlook_calendar_node"


def context(
    data: dict, credential_type: CredentialType = CredentialType.outlook_calendar
) -> NodeExecutionContext:
    executor = MagicMock()
    executor._get_accessible_credential.return_value = MagicMock(
        type=credential_type, encrypted_config="encrypted"
    )
    values = {
        "$input.email": "visitor@example.com",
        "$input.startTime": "2026-11-10T10:00:00Z",
        "$input.endTime": "2026-11-10T10:30:00Z",
        "$input.calendar": "Work",
        "$booking.event_id": "EVT-1",
    }
    executor.evaluate_message_template.side_effect = lambda value, *_: (
        values.get(value, value) if value else "{}"
    )
    return NodeExecutionContext(
        executor,
        "calendar",
        {},
        False,
        0.0,
        {"id": "calendar", "type": "outlookCalendar", "data": data},
        "outlookCalendar",
        data,
        "Calendar",
    )


class TestOutlookCalendarNode(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MagicMock()
        self.service_class = MagicMock(return_value=self.service)
        for target, kwargs in (
            (f"{_MODULE}.OutlookCalendarService", {"new": self.service_class}),
            (f"{_MODULE}.SessionLocal", {}),
            (f"{_MODULE}.decrypt_config", {"return_value": {"client_id": "dummy"}}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_read_defaults_do_not_resolve_blank_templates_into_inputs(self) -> None:
        execute(context({"credentialId": "credential", "ocEndDate": "", "ocTimeZone": ""}))

        self.service.read_availability.assert_called_once_with(
            "primary", "", "", "UTC", include_busy_details=False
        )
        self.assertEqual(self.service_class.call_args.args[0], "credential")

    def test_an_exchange_server_credential_uses_ews(self) -> None:
        config = {"auth_mode": "ews", "ews_email": "ada@heym.run"}
        exchange = MagicMock()
        with (
            patch(f"{_MODULE}.decrypt_config", return_value=config),
            patch(f"{_MODULE}.ExchangeCalendarService", return_value=exchange) as exchange_class,
        ):
            execute(context({"credentialId": "credential"}))

        exchange_class.assert_called_once_with(config)
        exchange.read_availability.assert_called_once()
        self.service_class.assert_not_called()

    def test_read_resolves_the_calendar_expression(self) -> None:
        execute(
            context(
                {
                    "credentialId": "credential",
                    "ocOperation": "read",
                    "ocCalendarId": "$input.calendar",
                    "ocTimeZone": "Europe/Berlin",
                    "ocStartDate": "2026-11-10",
                }
            )
        )

        self.service.read_availability.assert_called_once_with(
            "Work", "2026-11-10", "", "Europe/Berlin", include_busy_details=False
        )

    def test_checkbox_options_accept_booleans_and_agent_boolean_strings(self) -> None:
        for value, expected in (
            (True, True),
            (False, False),
            ("true", True),
            (" FALSE ", False),
            (None, False),
            ("", False),
        ):
            with self.subTest(value=value):
                self.service.reset_mock()
                execute(context({"credentialId": "credential", "ocIncludeBusyDetails": value}))
                self.assertIs(
                    self.service.read_availability.call_args.kwargs["include_busy_details"],
                    expected,
                )
        for value in ("yes", 1, ["true"]):
            with self.subTest(value=value), self.assertRaises(HTTPException) as caught:
                execute(context({"credentialId": "credential", "ocIncludeBusyDetails": value}))
            self.assertEqual(caught.exception.status_code, 400)

    def test_create_resolves_booking_fields_and_adds_teams_by_default(self) -> None:
        execute(
            context(
                {
                    "credentialId": "credential",
                    "ocOperation": "create",
                    "ocTitle": "Intro call",
                    "ocAttendees": "$input.email",
                    "ocStartTime": "$input.startTime",
                    "ocEndTime": "$input.endTime",
                }
            )
        )

        args = self.service.save_event.call_args
        self.assertEqual(args.args, ("create", "primary", ""))
        self.assertEqual(args.kwargs["title"], "Intro call")
        self.assertEqual(args.kwargs["attendees"], "visitor@example.com")
        self.assertEqual(args.kwargs["start"], "2026-11-10T10:00:00Z")
        self.assertEqual(args.kwargs["end"], "2026-11-10T10:30:00Z")
        self.assertEqual(args.kwargs["description"], "")
        self.assertIs(args.kwargs["teams_meeting"], True)

    def test_create_can_turn_teams_off_and_resolves_attendee_lists(self) -> None:
        execute(
            context(
                {
                    "credentialId": "credential",
                    "ocOperation": "create",
                    "ocTeamsMeeting": "false",
                    "ocAttendees": ["$input.email", "fixed@example.com"],
                }
            )
        )

        kwargs = self.service.save_event.call_args.kwargs
        self.assertIs(kwargs["teams_meeting"], False)
        self.assertEqual(kwargs["attendees"], ["visitor@example.com", "fixed@example.com"])

    def test_update_and_delete_use_the_resolved_event_id(self) -> None:
        execute(
            context(
                {
                    "credentialId": "credential",
                    "ocOperation": "update",
                    "ocEventId": "$booking.event_id",
                    "ocLocation": "Room 4",
                }
            )
        )
        self.assertEqual(self.service.save_event.call_args.args, ("update", "primary", "EVT-1"))
        self.assertEqual(self.service.save_event.call_args.kwargs["location"], "Room 4")

        execute(
            context(
                {
                    "credentialId": "credential",
                    "ocOperation": "delete",
                    "ocEventId": "$booking.event_id",
                }
            )
        )
        self.service.delete_event.assert_called_once_with("EVT-1")

    def test_missing_wrong_or_inaccessible_credentials_and_operations_are_refused(self) -> None:
        cases = (
            context({"ocOperation": "read"}),
            context({"credentialId": "credential", "ocOperation": "move"}),
            context({"credentialId": "credential"}, CredentialType.outlook),
            context({"credentialId": "credential"}, CredentialType.google_meet),
        )
        for ctx in cases:
            with self.subTest(data=ctx.node_data), self.assertRaises(HTTPException) as caught:
                execute(ctx)
            self.assertEqual(caught.exception.status_code, 400)
        inaccessible = context({"credentialId": "credential"})
        inaccessible.executor._get_accessible_credential.return_value = None
        with self.assertRaises(HTTPException):
            execute(inaccessible)
        self.service_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
