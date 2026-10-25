"""The collab bus: publishing with chunking, listening, resync and a real-Postgres pass."""

import asyncio
import json
import unittest
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.session import libpq_dsn
from app.services.collab.bus import CollabBus, CollabPublishError
from app.services.collab.hub import CollabConnection, CollabHub
from app.services.collab.protocol import RoutedMessage
from app.services.collab.saves import queue_collab_saved
from app.services.collab.wire import CHANNEL, encode_payloads

ROOM = "5d0c7b3a-8a1f-4a43-9a7e-0e6c1d2b3f40"


class _FakeConnection:
    """Stands in for an asyncpg connection."""

    def __init__(self) -> None:
        self.listeners: dict[str, Any] = {}
        self.executed: list[tuple[Any, ...]] = []
        self.transactions = 0
        self.closed = False
        self.fail = False
        self.probe_error: Exception | None = None

    async def add_listener(self, channel: str, callback: Any) -> None:
        self.listeners[channel] = callback

    async def execute(self, sql: str, *args: Any) -> None:
        if self.fail:
            raise ConnectionError("gone")
        if sql == "SELECT 1":
            if self.probe_error is not None:
                raise self.probe_error
            return
        self.executed.append((sql, *args))

    def transaction(self) -> Any:
        connection = self

        class _Transaction:
            async def __aenter__(self) -> None:
                connection.transactions += 1

            async def __aexit__(self, *_exc: Any) -> bool:
                return False

        return _Transaction()

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


def _drain(connection: CollabConnection) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not connection.queue.empty():
        frames.append(json.loads(connection.queue.get_nowait()))
    return frames


class BusPublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_small_message_is_one_notify_without_a_transaction(self) -> None:
        connection = _FakeConnection()
        bus = CollabBus(CollabHub(), connect=AsyncMock(return_value=connection))

        await bus.publish(ROOM, RoutedMessage(to=None, skip=None, data={"t": "cursor"}))

        self.assertEqual(0, connection.transactions)
        ((sql, channel, payload),) = connection.executed
        self.assertIn("pg_notify", sql)
        self.assertEqual(CHANNEL, channel)
        self.assertTrue(payload.startswith(f"{ROOM}|"))

    async def test_a_large_message_is_chunked_inside_one_transaction(self) -> None:
        connection = _FakeConnection()
        bus = CollabBus(CollabHub(), connect=AsyncMock(return_value=connection))

        await bus.publish(
            ROOM, RoutedMessage(to=None, skip=None, data={"t": "snapshot", "blob": "x" * 20000})
        )

        self.assertEqual(1, connection.transactions)
        self.assertEqual(3, len(connection.executed))

    async def test_a_failed_publish_reconnects_next_time(self) -> None:
        broken, healthy = _FakeConnection(), _FakeConnection()
        broken.fail = True
        bus = CollabBus(CollabHub(), connect=AsyncMock(side_effect=[broken, healthy]))
        message = RoutedMessage(to=None, skip=None, data={"t": "cursor"})

        with self.assertRaises(CollabPublishError):
            await bus.publish(ROOM, message)
        await bus.publish(ROOM, message)

        self.assertTrue(broken.closed)
        self.assertEqual(1, len(healthy.executed))


class BusListenTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivers_a_reassembled_message_to_local_sockets(self) -> None:
        hub = CollabHub()
        socket = CollabConnection("sid-a")
        hub.add(ROOM, socket)
        bus = CollabBus(hub, connect=AsyncMock())
        wire = RoutedMessage(to=None, skip=None, data={"t": "snapshot", "blob": "é" * 9000})
        payloads = encode_payloads(ROOM, wire.to_wire())

        results = [bus.handle_payload(payload, now=0.0) for payload in payloads]

        self.assertEqual([0] * (len(payloads) - 1) + [1], results)
        self.assertEqual("é" * 9000, _drain(socket)[0]["blob"])

    async def test_ignores_rooms_without_local_sockets(self) -> None:
        bus = CollabBus(CollabHub(), connect=AsyncMock())
        wire = RoutedMessage(to=None, skip=None, data={"t": "cursor"}).to_wire()

        self.assertEqual(0, bus.handle_payload(encode_payloads(ROOM, wire)[0]))

    async def test_listens_and_resyncs_after_a_reconnect(self) -> None:
        first, second = _FakeConnection(), _FakeConnection()
        first.probe_error = ConnectionError("dropped")
        hub = CollabHub()
        socket = CollabConnection("sid-a")
        hub.add(ROOM, socket)
        bus = CollabBus(hub, connect=AsyncMock(side_effect=[first, second]))

        with (
            patch("app.services.collab.bus._CONNECTION_PROBE_SECONDS", 0.01),
            patch("app.services.collab.bus._RECONNECT_DELAY_SECONDS", 0.01),
        ):
            self.assertTrue(await bus.ensure_started(timeout=1.0))
            await asyncio.sleep(0.1)
        await bus.stop()

        self.assertEqual([CHANNEL], list(second.listeners))
        self.assertGreaterEqual(_drain(socket).count({"t": "resync"}), 2)


async def _postgres_reachable() -> bool:
    try:
        connection = await asyncpg.connect(libpq_dsn(), timeout=3)
    except Exception:
        return False
    await connection.close()
    return True


class RealPostgresCollabTests(unittest.IsolatedAsyncioTestCase):
    """NOTIFY through a real server; skipped when none is reachable."""

    async def asyncSetUp(self) -> None:
        if not await _postgres_reachable():
            self.skipTest("PostgreSQL is not reachable")
        self.hub = CollabHub()
        self.socket = CollabConnection("sid-a")
        self.hub.add(ROOM, self.socket)
        self.bus = CollabBus(self.hub)
        self.addAsyncCleanup(self.bus.stop)
        self.assertTrue(await self.bus.ensure_started(timeout=5.0))

    async def _next_frame(self) -> dict[str, Any]:
        while True:
            frame = json.loads(await self.socket.queue.get())
            if frame.get("t") != "resync":
                return frame

    async def test_a_chunked_message_crosses_postgres_intact(self) -> None:
        blob = "é😀" * 6000

        await self.bus.publish(
            ROOM, RoutedMessage(to=None, skip=None, data={"t": "snapshot", "blob": blob})
        )

        frame = await asyncio.wait_for(self._next_frame(), timeout=5.0)
        self.assertEqual(blob, frame["blob"])

    async def test_a_save_notifies_the_room_when_it_commits(self) -> None:
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        self.addAsyncCleanup(engine.dispose)
        session_id = str(uuid.uuid4())

        async with AsyncSession(engine) as db:
            await queue_collab_saved(
                db, uuid.UUID(ROOM), uuid.uuid4(), session=session_id, state_hash="abc123"
            )
            await db.commit()

        frame = await asyncio.wait_for(self._next_frame(), timeout=5.0)
        self.assertEqual("saved", frame["t"])
        self.assertEqual(session_id, frame["sid"])
        self.assertEqual("abc123", frame["hash"])
        self.assertRegex(frame["updatedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
