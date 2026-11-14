"""Node dispatch, dynamic booking fields and accessible credential checks."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.db.models import CredentialType
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.google_meet_node import execute


def context(data: dict) -> NodeExecutionContext:
    executor = MagicMock()
    executor._get_accessible_credential.return_value = MagicMock(
        type=CredentialType.google_meet, encrypted_config="encrypted"
    )
    values = {
        "$input.email": "visitor@example.com",
        "$input.startTime": "2026-11-10T10:00:00Z",
        "$input.endTime": "2026-11-10T10:30:00Z",
        "$input.title": 'Call with "visitor"',
    }
    executor.evaluate_message_template.side_effect = lambda value, *_: (
        values.get(value, value) if value else "{}"
    )
    return NodeExecutionContext(
        executor,
        "meet",
        {},
        False,
        0.0,
        {"id": "meet", "type": "googleMeet", "data": data},
        "googleMeet",
        data,
        "Meeting",
    )


class TestGoogleMeetNode(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MagicMock()
        for target, kwargs in (
            (
                "app.services.node_execution.nodes.google_meet_node.GoogleMeetService",
                {"return_value": self.service},
            ),
            ("app.services.node_execution.nodes.google_meet_node.SessionLocal", {}),
            (
                "app.services.node_execution.nodes.google_meet_node.decrypt_config",
                {"return_value": {"client_id": "dummy"}},
            ),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_read_defaults_do_not_resolve_blank_templates_into_inputs(self) -> None:
        execute(context({"credentialId": "credential", "gmOperation": "read", "gmEndDate": ""}))
        self.service.read_availability.assert_called_once_with(
            "primary", "", "", "UTC", include_busy_details=False
        )

    def test_busy_details_opt_in_accepts_boolean_and_agent_boolean_strings(self) -> None:
        for value, expected in (
            (True, True),
            (False, False),
            ("true", True),
            ("false", False),
            (None, False),
        ):
            with self.subTest(value=value):
                self.service.reset_mock()
                execute(context({"credentialId": "credential", "gmIncludeBusyDetails": value}))
                self.assertIs(
                    self.service.read_availability.call_args.kwargs["include_busy_details"],
                    expected,
                )

    def test_legacy_busy_titles_opt_in_continues_working(self) -> None:
        for value, expected in (
            (True, True),
            (False, False),
            ("true", True),
            ("false", False),
        ):
            with self.subTest(value=value):
                self.service.reset_mock()
                execute(context({"credentialId": "credential", "gmIncludeBusyTitles": value}))
                self.assertIs(
                    self.service.read_availability.call_args.kwargs["include_busy_details"],
                    expected,
                )

    def test_new_details_key_takes_precedence_over_legacy_key(self) -> None:
        for details_val, titles_val, expected in (
            (False, True, False),
            ("false", True, False),
            (None, True, False),
            (None, "true", False),
            (True, False, True),
            ("true", False, True),
            (False, "true", False),
            (True, "false", True),
        ):
            with self.subTest(details=details_val, titles=titles_val):
                self.service.reset_mock()
                execute(
                    context(
                        {
                            "credentialId": "credential",
                            "gmIncludeBusyDetails": details_val,
                            "gmIncludeBusyTitles": titles_val,
                        }
                    )
                )
                self.assertIs(
                    self.service.read_availability.call_args.kwargs["include_busy_details"],
                    expected,
                )

    def test_explicit_null_details_key_takes_precedence_over_legacy_true(self) -> None:
        for titles_val in (True, "true"):
            with self.subTest(titles_val=titles_val):
                self.service.reset_mock()
                execute(
                    context(
                        {
                            "credentialId": "credential",
                            "gmIncludeBusyDetails": None,
                            "gmIncludeBusyTitles": titles_val,
                        }
                    )
                )
                self.assertIs(
                    self.service.read_availability.call_args.kwargs["include_busy_details"],
                    False,
                )

    def test_invalid_details_opt_in_never_silently_enables_reads(self) -> None:
        for key in ("gmIncludeBusyDetails", "gmIncludeBusyTitles"):
            for value in ("anything", "1", 1, [], {}):
                with self.subTest(key=key, value=value), self.assertRaises(HTTPException) as cm:
                    execute(context({"credentialId": "credential", key: value}))
                self.assertEqual(cm.exception.status_code, 400)
                self.assertEqual(
                    cm.exception.detail,
                    "Google Meet: Include Busy Event Details must be true or false",
                )
        self.service.read_availability.assert_not_called()

    def test_create_invites_parameter_email_from_connected_owner_account(self) -> None:
        ctx = context(
            {
                "credentialId": "owner-credential",
                "gmOperation": "create",
                "gmTitle": "$input.title",
                "gmAttendees": "$input.email",
                "gmStartTime": "$input.startTime",
                "gmEndTime": "$input.endTime",
            }
        )
        execute(ctx)
        self.service.save_event.assert_called_once_with(
            "create",
            "primary",
            "",
            title='Call with "visitor"',
            description="",
            start="2026-11-10T10:00:00Z",
            end="2026-11-10T10:30:00Z",
            time_zone="UTC",
            attendees="visitor@example.com",
            location="",
        )
        ctx.executor._get_accessible_credential.assert_called_once()

    def test_attendee_array_resolves_expressions_per_address(self) -> None:
        execute(
            context(
                {
                    "credentialId": "credential",
                    "gmOperation": "create",
                    "gmAttendees": ["$input.email", "host@example.com"],
                }
            )
        )
        self.assertEqual(
            self.service.save_event.call_args.kwargs["attendees"],
            ["visitor@example.com", "host@example.com"],
        )

    def test_update_and_delete_use_resolved_event_ids(self) -> None:
        for operation in ("update", "delete"):
            with self.subTest(operation=operation):
                execute(
                    context(
                        {
                            "credentialId": "credential",
                            "gmOperation": operation,
                            "gmEventId": "event-1",
                        }
                    )
                )
        self.service.delete_event.assert_called_once_with("primary", "event-1")
        self.assertEqual(self.service.save_event.call_args.args, ("update", "primary", "event-1"))

    def test_missing_or_wrong_type_credentials_are_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            execute(context({}))
        for credential in (None, MagicMock(type=CredentialType.google_drive)):
            with self.subTest(credential=credential), self.assertRaises(HTTPException):
                ctx = context({"credentialId": "credential"})
                ctx.executor._get_accessible_credential.return_value = credential
                execute(ctx)
        self.service.read_availability.assert_not_called()

    def test_unknown_operation_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            execute(context({"credentialId": "credential", "gmOperation": "unknown"}))

    def test_node_is_registered_credential_backed_and_cluster_portable(self) -> None:
        from app.services.cluster.node_placement import NODE_PLACEMENT, Placement
        from app.services.credential_catalog import NODE_CREDENTIAL_FIELDS
        from app.services.node_execution.registry import get_node_handler

        self.assertIs(get_node_handler("googleMeet"), execute)
        self.assertEqual(NODE_PLACEMENT["googleMeet"], Placement.ANYWHERE)
        self.assertEqual(
            NODE_CREDENTIAL_FIELDS["googleMeet"][0].types, frozenset({CredentialType.google_meet})
        )
