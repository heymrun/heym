"""A2A 1.0 wire format: ProtoJSON names, one member per stream event, error envelopes."""

import unittest

from app.services.a2a import errors
from app.services.a2a.models import (
    Message,
    Role,
    SecurityRequirement,
    StreamResponse,
    StringList,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from app.services.a2a.version import check_version


class WireTests(unittest.TestCase):
    def test_task_uses_camel_case_and_proto_enum_names(self) -> None:
        task = Task(id="t1", context_id="c1", status=TaskStatus(state=TaskState.WORKING))

        self.assertEqual(
            task.wire(),
            {"id": "t1", "contextId": "c1", "status": {"state": "TASK_STATE_WORKING"}},
        )

    def test_message_parses_wire_names(self) -> None:
        message = Message.model_validate(
            {
                "messageId": "m1",
                "role": "ROLE_USER",
                "contextId": "c1",
                "taskId": "t1",
                "parts": [{"text": "hi"}, {"data": {"a": 1}}],
            }
        )

        self.assertEqual(message.role, Role.USER)
        self.assertEqual(message.task_id, "t1")
        self.assertEqual(message.parts[1].data, {"a": 1})

    def test_stream_response_carries_one_member(self) -> None:
        event = StreamResponse(
            status_update=TaskStatusUpdateEvent(
                task_id="t1", context_id="c1", status=TaskStatus(state=TaskState.COMPLETED)
            )
        )

        self.assertEqual(list(event.wire()), ["statusUpdate"])

    def test_security_requirement_lists_scopes_under_list(self) -> None:
        requirement = SecurityRequirement(schemes={"heymApiKey": StringList()})

        self.assertEqual(requirement.wire(), {"schemes": {"heymApiKey": {"list": []}}})


class ErrorTests(unittest.TestCase):
    def test_error_envelope(self) -> None:
        self.assertEqual(
            errors.jsonrpc_error(3, errors.task_not_found()),
            {"jsonrpc": "2.0", "id": 3, "error": {"code": -32001, "message": "Task not found."}},
        )

    def test_codes_follow_the_json_rpc_binding(self) -> None:
        self.assertEqual(errors.task_not_cancelable().code, -32002)
        self.assertEqual(errors.push_not_supported().code, -32003)
        self.assertEqual(errors.unsupported("x").code, -32004)
        self.assertEqual(errors.content_type_not_supported().code, -32005)
        self.assertEqual(errors.invalid_params("x").code, -32602)


class VersionTests(unittest.TestCase):
    def test_1_0_and_missing_header_are_accepted_for_1_0_methods(self) -> None:
        for value in ("1.0", "1.0.2", "", None):
            with self.subTest(value=value):
                check_version(value, "SendMessage")

    def test_other_versions_are_refused(self) -> None:
        for value in ("0.3", "2.0"):
            with self.subTest(value=value), self.assertRaises(errors.A2AError) as caught:
                check_version(value, "SendMessage")
            self.assertEqual(caught.exception.code, errors.VERSION_NOT_SUPPORTED)

    def test_0_3_method_names_are_refused_without_a_header(self) -> None:
        with self.assertRaises(errors.A2AError) as caught:
            check_version(None, "message/send")

        self.assertEqual(caught.exception.code, errors.VERSION_NOT_SUPPORTED)
