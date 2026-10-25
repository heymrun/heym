"""The process-local registry that hands bus messages to sockets."""

import json
import unittest
from typing import Any

from app.services.collab.hub import CollabConnection, CollabHub
from app.services.collab.protocol import RoutedMessage

ROOM = "room-1"


def _drain(connection: CollabConnection) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not connection.queue.empty():
        frames.append(json.loads(connection.queue.get_nowait()))
    return frames


class HubDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = CollabHub(max_room_sockets=2)
        self.a = CollabConnection("sid-a")
        self.b = CollabConnection("sid-b")
        self.assertTrue(self.hub.add(ROOM, self.a))
        self.assertTrue(self.hub.add(ROOM, self.b))

    def test_skip_excludes_the_sender(self) -> None:
        wire = RoutedMessage(to=None, skip="sid-a", data={"t": "cursor"}).to_wire()

        self.assertEqual(1, self.hub.deliver(ROOM, wire))
        self.assertEqual([], _drain(self.a))
        self.assertEqual([{"t": "cursor"}], _drain(self.b))

    def test_to_reaches_only_the_target(self) -> None:
        wire = RoutedMessage(to="sid-b", skip=None, data={"t": "signal"}).to_wire()

        self.assertEqual(1, self.hub.deliver(ROOM, wire))
        self.assertEqual([], _drain(self.a))
        self.assertEqual([{"t": "signal"}], _drain(self.b))

    def test_other_rooms_and_malformed_wire_are_ignored(self) -> None:
        wire = RoutedMessage(to=None, skip=None, data={"t": "ops"}).to_wire()

        self.assertEqual(0, self.hub.deliver("room-2", wire))
        self.assertEqual(0, self.hub.deliver(ROOM, "not json"))
        self.assertEqual(0, self.hub.deliver(ROOM, '{"data": 3}'))
        self.assertEqual([], _drain(self.a))

    def test_a_full_room_refuses_another_socket(self) -> None:
        self.assertFalse(self.hub.add(ROOM, CollabConnection("sid-c")))
        self.assertEqual(2, self.hub.room_size(ROOM))

    def test_removing_the_last_socket_drops_the_room(self) -> None:
        self.hub.remove(ROOM, "sid-a")
        self.hub.remove(ROOM, "sid-b")

        self.assertFalse(self.hub.has_room(ROOM))

    def test_resync_reaches_every_local_socket(self) -> None:
        self.assertEqual(2, self.hub.broadcast_resync())
        self.assertEqual([{"t": "resync"}], _drain(self.a))
        self.assertEqual([{"t": "resync"}], _drain(self.b))


class ConnectionBackpressureTests(unittest.TestCase):
    def test_a_full_queue_marks_the_socket_too_slow(self) -> None:
        connection = CollabConnection("sid", queue_size=1)

        connection.enqueue("first")
        connection.enqueue("second")

        self.assertTrue(connection.overflowed)
        self.assertEqual(1, connection.queue.qsize())
