"""Process-local registry of canvas collaboration sockets, by room.

``deliver`` runs on the bus listener's callback for every message any process published to a
room this process has sockets in. It only enqueues: each socket's writer task drains its own
queue, so one slow browser never delays the others.
"""

from __future__ import annotations

import asyncio
import json

from app.services.collab.protocol import MAX_ROOM_SOCKETS, server_message

OUTBOUND_QUEUE_SIZE = 1000


class CollabConnection:
    """The outbound side of one socket."""

    def __init__(self, sid: str, queue_size: int = OUTBOUND_QUEUE_SIZE) -> None:
        self.sid = sid
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size)
        self.overflowed = False

    def enqueue(self, text: str) -> None:
        """Queue a frame; a full queue marks the socket as too slow to keep."""
        if self.overflowed:
            return
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            self.overflowed = True


class CollabHub:
    """Rooms and their sockets on this process."""

    def __init__(self, max_room_sockets: int = MAX_ROOM_SOCKETS) -> None:
        self._max_room_sockets = max_room_sockets
        self._rooms: dict[str, dict[str, CollabConnection]] = {}

    def has_room(self, room: str) -> bool:
        """True when this process has at least one socket in ``room``."""
        return room in self._rooms

    def room_size(self, room: str) -> int:
        """Sockets in ``room`` on this process."""
        return len(self._rooms.get(room, {}))

    def add(self, room: str, connection: CollabConnection) -> bool:
        """Register a socket; False when the room is full on this process."""
        if self.room_size(room) >= self._max_room_sockets:
            return False
        self._rooms.setdefault(room, {})[connection.sid] = connection
        return True

    def remove(self, room: str, sid: str) -> None:
        """Forget a socket; the room goes away with its last socket."""
        sockets = self._rooms.get(room)
        if sockets is None:
            return
        sockets.pop(sid, None)
        if not sockets:
            self._rooms.pop(room, None)

    def deliver(self, room: str, wire_text: str) -> int:
        """Enqueue a bus message for the local sockets it addresses. Returns how many."""
        sockets = self._rooms.get(room)
        if not sockets:
            return 0
        try:
            envelope = json.loads(wire_text)
        except json.JSONDecodeError:
            return 0
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict):
            return 0
        target, skip = envelope.get("to"), envelope.get("skip")
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        delivered = 0
        for sid, connection in tuple(sockets.items()):
            if target is not None and sid != target:
                continue
            if skip is not None and sid == skip:
                continue
            connection.enqueue(text)
            delivered += 1
        return delivered

    def broadcast_resync(self) -> int:
        """Tell every local socket that messages may have been missed."""
        text = server_message("resync")
        count = 0
        for sockets in tuple(self._rooms.values()):
            for connection in tuple(sockets.values()):
                connection.enqueue(text)
                count += 1
        return count


collab_hub = CollabHub()
