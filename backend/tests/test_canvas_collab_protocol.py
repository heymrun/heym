"""What a canvas session may send and where it goes."""

import json
import unittest
import uuid

from app.services.collab.protocol import (
    ProtocolError,
    RateLimiter,
    SessionIdentity,
    parse_collab_hash_header,
    parse_collab_session_header,
    route_client_message,
)

WRITER = SessionIdentity(
    sid=str(uuid.uuid4()), user_id=str(uuid.uuid4()), name="Ana", permission="write"
)
READER = SessionIdentity(
    sid=str(uuid.uuid4()), user_id=str(uuid.uuid4()), name="Ben", permission="read"
)


class RouteClientMessageTests(unittest.TestCase):
    def test_the_server_stamp_replaces_a_forged_sender(self) -> None:
        forged = {"sid": "x", "userId": "someone-else", "name": "Mallory", "permission": "write"}

        routed = route_client_message(
            json.dumps({"t": "presence", "state": {}, "from": forged}), READER
        )

        self.assertEqual(READER.stamp(), routed.data["from"])
        self.assertEqual({}, routed.data["state"])

    def test_presence_and_cursor_skip_the_sender(self) -> None:
        for frame in ({"t": "presence", "state": {}}, {"t": "cursor", "x": 1, "y": 2}):
            routed = route_client_message(json.dumps(frame), READER)
            self.assertEqual(READER.sid, routed.skip)
            self.assertIsNone(routed.to)

    def test_an_assistant_transcript_reaches_the_room_from_any_session(self) -> None:
        routed = route_client_message(
            json.dumps(
                {"t": "assistant", "messages": [{"id": "1", "role": "user", "content": "hi"}]}
            ),
            READER,
        )

        self.assertEqual(READER.sid, routed.skip)
        self.assertIsNone(routed.to)
        self.assertEqual("hi", routed.data["messages"][0]["content"])

    def test_a_dialog_interaction_reaches_the_room_from_any_session(self) -> None:
        frame = {"t": "ui", "action": "click", "target": {"key": "Share", "tag": "button"}}

        routed = route_client_message(json.dumps(frame), READER)

        self.assertEqual(READER.sid, routed.skip)
        self.assertEqual("click", routed.data["action"])

    def test_ops_and_reload_come_back_to_the_sender(self) -> None:
        for frame in ({"t": "ops", "seq": 1, "ops": []}, {"t": "reload"}):
            routed = route_client_message(json.dumps(frame), WRITER)
            self.assertIsNone(routed.skip)
            self.assertIsNone(routed.to)

    def test_read_sessions_cannot_change_the_draft(self) -> None:
        target = str(uuid.uuid4())
        for frame in (
            {"t": "ops", "seq": 1, "ops": []},
            {"t": "snapshot", "to": target, "nodes": [], "edges": []},
            {"t": "reload"},
        ):
            with self.assertRaisesRegex(ProtocolError, "write access"):
                route_client_message(json.dumps(frame), READER)

    def test_targeted_messages_need_a_valid_session(self) -> None:
        for to in (None, "", "not-a-uuid"):
            with self.assertRaisesRegex(ProtocolError, "target session"):
                route_client_message(json.dumps({"t": "signal", "to": to, "data": {}}), READER)

    def test_a_targeted_message_goes_only_to_its_target(self) -> None:
        target = str(uuid.uuid4())

        routed = route_client_message(json.dumps({"t": "signal", "to": target, "data": {}}), READER)

        self.assertEqual(target, routed.to)
        self.assertIsNone(routed.skip)
        self.assertEqual(target, routed.data["to"])

    def test_unknown_and_malformed_frames_are_refused(self) -> None:
        for raw in ("not json", "[]", "{}", '{"t": 5}', '{"t": "drop_tables"}'):
            with self.assertRaises(ProtocolError):
                route_client_message(raw, WRITER)

    def test_wire_form_carries_routing_and_data(self) -> None:
        routed = route_client_message(json.dumps({"t": "cursor", "x": 1, "y": 2}), WRITER)

        wire = json.loads(routed.to_wire())

        self.assertEqual({"to", "skip", "data"}, set(wire))
        self.assertEqual("cursor", wire["data"]["t"])


class RateLimiterTests(unittest.TestCase):
    def test_burst_then_refusal_then_recovery(self) -> None:
        limiter = RateLimiter(rate=10.0, burst=3.0, tokens=3.0, updated_at=0.0)

        self.assertEqual([True, True, True, False], [limiter.allow(0.0) for _ in range(4)])
        self.assertTrue(limiter.allow(0.2))

    def test_sustained_excess_is_reported_after_three_seconds(self) -> None:
        limiter = RateLimiter(rate=1.0, burst=1.0, tokens=0.0, updated_at=0.0)

        self.assertFalse(limiter.allow(0.0))
        self.assertFalse(limiter.sustained_excess(2.9))
        self.assertTrue(limiter.sustained_excess(3.0))


class HeaderParsingTests(unittest.TestCase):
    def test_session_header(self) -> None:
        sid = str(uuid.uuid4())
        self.assertEqual(sid, parse_collab_session_header(sid))
        self.assertEqual(sid, parse_collab_session_header(sid.upper()))
        self.assertIsNone(parse_collab_session_header("nope"))
        self.assertIsNone(parse_collab_session_header(None))

    def test_hash_header(self) -> None:
        self.assertEqual("k3x9a1", parse_collab_hash_header("k3x9a1"))
        for bad in ("UPPER", "a" * 33, "", "with space", None):
            self.assertIsNone(parse_collab_hash_header(bad), bad)
