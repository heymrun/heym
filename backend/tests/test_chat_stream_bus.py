"""Chat streams share one LISTEN connection per process instead of one per stream.

Covers the bus itself (routing, reconnect, readiness), the registry on top of it
(publish, subscribe, replay, polling fallback), and a real-PostgreSQL pass that
proves a notification actually crosses the wire and survives a killed listener.
"""

import asyncio
import contextlib
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg

from app.db.session import libpq_dsn, listener_server_settings
from app.services import chat_task_registry as registry
from app.services.chat_stream_bus import CHANNEL, ChatStreamBus


class _FakeConnection:
    """Stands in for an asyncpg connection that holds LISTEN channels."""

    def __init__(self) -> None:
        self.listeners: dict[str, Any] = {}
        self.closed = False
        self.probe_error: Exception | None = None

    async def add_listener(self, channel: str, callback: Any) -> None:
        self.listeners[channel] = callback

    async def execute(self, _sql: str) -> None:
        if self.probe_error is not None:
            raise self.probe_error

    async def close(self) -> None:
        self.closed = True


class BusRoutingTests(unittest.TestCase):
    def test_notification_wakes_only_the_named_conversation(self) -> None:
        bus = ChatStreamBus()
        mine, other = asyncio.Event(), asyncio.Event()
        bus.register("conv-a", mine)
        bus.register("conv-b", other)

        woken = bus.handle_payload("conv-a")

        self.assertEqual(1, woken)
        self.assertTrue(mine.is_set())
        self.assertFalse(other.is_set())

    def test_payload_match_ignores_case_and_whitespace(self) -> None:
        bus = ChatStreamBus()
        event = asyncio.Event()
        bus.register("ABC-123", event)

        self.assertEqual(1, bus.handle_payload("  abc-123\n"))
        self.assertTrue(event.is_set())

    def test_unknown_conversation_wakes_nobody(self) -> None:
        bus = ChatStreamBus()

        self.assertEqual(0, bus.handle_payload("nobody"))

    def test_every_subscriber_of_one_conversation_wakes(self) -> None:
        bus = ChatStreamBus()
        first, second = asyncio.Event(), asyncio.Event()
        bus.register("conv", first)
        bus.register("conv", second)

        self.assertEqual(2, bus.handle_payload("conv"))
        self.assertTrue(first.is_set() and second.is_set())

    def test_unregister_removes_only_that_subscriber(self) -> None:
        bus = ChatStreamBus()
        first, second = asyncio.Event(), asyncio.Event()
        bus.register("conv", first)
        bus.register("conv", second)

        bus.unregister("conv", first)
        bus.handle_payload("conv")

        self.assertFalse(first.is_set())
        self.assertTrue(second.is_set())
        self.assertEqual(1, bus.subscriber_count())

    def test_last_unregister_drops_the_conversation_entry(self) -> None:
        bus = ChatStreamBus()
        event = asyncio.Event()
        bus.register("conv", event)

        bus.unregister("conv", event)

        self.assertEqual(0, bus.subscriber_count())
        self.assertEqual({}, bus._waiters)

    def test_unregister_of_unknown_subscriber_is_harmless(self) -> None:
        bus = ChatStreamBus()

        bus.unregister("never-registered", asyncio.Event())

    def test_wake_all_reaches_every_conversation(self) -> None:
        bus = ChatStreamBus()
        events = [asyncio.Event() for _ in range(3)]
        for index, event in enumerate(events):
            bus.register(f"conv-{index}", event)

        bus.wake_all()

        self.assertTrue(all(event.is_set() for event in events))

    def test_listener_connections_carry_the_instance_tag(self) -> None:
        settings = listener_server_settings()

        self.assertTrue(settings["application_name"].startswith("heym-"))

    def test_cancel_notification_invokes_registered_handler(self) -> None:
        bus = ChatStreamBus()
        called_args: list[tuple[uuid.UUID, uuid.UUID | None]] = []

        def handler(conv_id: uuid.UUID, run_id: uuid.UUID | None) -> None:
            called_args.append((conv_id, run_id))

        bus.register_cancel_handler(handler)
        conv_id = uuid.uuid4()
        bus.handle_payload(f"cancel:{conv_id}")

        self.assertEqual(len(called_args), 1)
        self.assertEqual(called_args[0][0], conv_id)
        self.assertIsNone(called_args[0][1])

    def test_cancel_notification_with_run_id_invokes_registered_handler(self) -> None:
        bus = ChatStreamBus()
        called_args: list[tuple[uuid.UUID, uuid.UUID | None]] = []

        def handler(conv_id: uuid.UUID, run_id: uuid.UUID | None) -> None:
            called_args.append((conv_id, run_id))

        bus.register_cancel_handler(handler)
        conv_id = uuid.uuid4()
        run_id = uuid.uuid4()
        bus.handle_payload(f"cancel:{conv_id}:{run_id}")

        self.assertEqual(len(called_args), 1)
        self.assertEqual(called_args[0], (conv_id, run_id))

    def test_cancel_notification_ignores_invalid_uuid(self) -> None:
        bus = ChatStreamBus()
        called = False

        def handler(_conv_id: uuid.UUID, _run_id: uuid.UUID | None) -> None:
            nonlocal called
            called = True

        bus.register_cancel_handler(handler)
        bus.handle_payload("cancel:not-a-valid-uuid")

        self.assertFalse(called)

    def test_cancel_notification_wakes_sse_subscribers(self) -> None:
        bus = ChatStreamBus()
        event = asyncio.Event()
        conv_id = str(uuid.uuid4())
        bus.register(conv_id, event)

        woken = bus.handle_payload(f"cancel:{conv_id}")

        self.assertEqual(woken, 1)
        self.assertTrue(event.is_set())

    def test_unregister_cancel_handler(self) -> None:
        bus = ChatStreamBus()
        call_count = 0

        def handler(_conv_id: uuid.UUID, _run_id: uuid.UUID | None) -> None:
            nonlocal call_count
            call_count += 1

        bus.register_cancel_handler(handler)
        conv_id = str(uuid.uuid4())
        bus.handle_payload(f"cancel:{conv_id}")
        self.assertEqual(call_count, 1)

        bus.unregister_cancel_handler(handler)
        bus.handle_payload(f"cancel:{conv_id}")
        self.assertEqual(call_count, 1)


class BusListenLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = ChatStreamBus()
        self.addAsyncCleanup(self.bus.stop)

    async def test_connects_with_instance_tag_and_listens_on_the_shared_channel(self) -> None:
        connection = _FakeConnection()
        connect = AsyncMock(return_value=connection)

        with patch("app.services.chat_stream_bus.asyncpg.connect", connect):
            await self.bus.start()
            self.assertTrue(await self.bus.wait_until_listening(1.0))

        connect.assert_awaited_once_with(libpq_dsn(), server_settings=listener_server_settings())
        self.assertEqual([CHANNEL], list(connection.listeners))
        self.assertTrue(self.bus.is_connected)

    async def test_a_delivered_notification_wakes_the_subscriber(self) -> None:
        connection = _FakeConnection()
        event = asyncio.Event()
        self.bus.register("conv", event)

        with patch(
            "app.services.chat_stream_bus.asyncpg.connect", AsyncMock(return_value=connection)
        ):
            await self.bus.start()
            await self.bus.wait_until_listening(1.0)
            event.clear()  # drop the catch-up wake from the connect itself
            connection.listeners[CHANNEL](connection, 1, CHANNEL, "conv")

        self.assertTrue(event.is_set())

    async def test_connecting_wakes_existing_subscribers_to_catch_up(self) -> None:
        event = asyncio.Event()
        self.bus.register("conv", event)

        with patch(
            "app.services.chat_stream_bus.asyncpg.connect",
            AsyncMock(return_value=_FakeConnection()),
        ):
            await self.bus.start()
            await self.bus.wait_until_listening(1.0)

        self.assertTrue(event.is_set())

    async def test_start_twice_keeps_a_single_listen_task(self) -> None:
        connect = AsyncMock(return_value=_FakeConnection())

        with patch("app.services.chat_stream_bus.asyncpg.connect", connect):
            await self.bus.start()
            first_task = self.bus._task
            await self.bus.start()
            await self.bus.wait_until_listening(1.0)

        self.assertIs(first_task, self.bus._task)
        self.assertEqual(1, connect.await_count)

    async def test_connection_failure_is_retried_not_fatal(self) -> None:
        attempts = 0

        async def connect(_dsn: str, **_kwargs: Any) -> _FakeConnection:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("connection refused")
            return _FakeConnection()

        with (
            patch("app.services.chat_stream_bus.asyncpg.connect", connect),
            patch("app.services.chat_stream_bus._RECONNECT_DELAY_SECONDS", 0),
        ):
            await self.bus.start()
            self.assertTrue(await self.bus.wait_until_listening(1.0))

        self.assertEqual(3, attempts)

    async def test_dead_connection_is_replaced_and_subscribers_catch_up(self) -> None:
        connections: list[_FakeConnection] = []

        async def connect(_dsn: str, **_kwargs: Any) -> _FakeConnection:
            connection = _FakeConnection()
            connections.append(connection)
            return connection

        event = asyncio.Event()
        self.bus.register("conv", event)

        with (
            patch("app.services.chat_stream_bus.asyncpg.connect", connect),
            patch("app.services.chat_stream_bus._RECONNECT_DELAY_SECONDS", 0),
            patch("app.services.chat_stream_bus._CONNECTION_PROBE_SECONDS", 0.01),
        ):
            await self.bus.start()
            await self.bus.wait_until_listening(1.0)
            event.clear()  # drop the catch-up wake from the first connect
            connections[0].probe_error = ConnectionError("server closed the connection")
            for _ in range(200):
                if len(connections) >= 2 and self.bus.is_connected:
                    break
                await asyncio.sleep(0.01)

        self.assertGreaterEqual(len(connections), 2)
        self.assertTrue(connections[0].closed)
        self.assertEqual([CHANNEL], list(connections[1].listeners))
        # Notifications sent while the old connection was dying are gone, so the
        # replacement must send subscribers back to the table.
        self.assertTrue(event.is_set())

    async def test_stop_closes_the_connection_and_clears_state(self) -> None:
        connection = _FakeConnection()

        with patch(
            "app.services.chat_stream_bus.asyncpg.connect", AsyncMock(return_value=connection)
        ):
            await self.bus.start()
            await self.bus.wait_until_listening(1.0)
            await self.bus.stop()

        self.assertTrue(connection.closed)
        self.assertFalse(self.bus.is_connected)
        self.assertIsNone(self.bus._task)

    async def test_wait_until_listening_reports_false_when_the_database_is_down(self) -> None:
        async def connect(_dsn: str, **_kwargs: Any) -> _FakeConnection:
            raise OSError("connection refused")

        with (
            patch("app.services.chat_stream_bus.asyncpg.connect", connect),
            patch("app.services.chat_stream_bus._RECONNECT_DELAY_SECONDS", 0.01),
        ):
            await self.bus.start()
            self.assertFalse(await self.bus.wait_until_listening(0.05))

        self.assertFalse(self.bus.is_connected)

    async def test_wait_until_listening_before_start_is_false(self) -> None:
        self.assertFalse(await self.bus.wait_until_listening(0.01))


class _Store:
    """In-memory stand-in for the ``chat_stream_events`` table and its NOTIFY queue."""

    def __init__(self) -> None:
        self.events: list[SimpleNamespace] = []
        self.notifies: list[tuple[str, str]] = []
        self.task_exists = True
        self._sequence = 0
        self.deliver: Any = None

    def insert(self, conv_id: str, payload: str, is_done: bool) -> None:
        self._sequence += 1
        self.events.append(
            SimpleNamespace(
                sequence=self._sequence, conv_id=conv_id, payload=payload, is_done=is_done
            )
        )


class _FakeResult:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar(self) -> Any:
        return self._scalar


class _FakeSession:
    def __init__(self, store: _Store) -> None:
        self._store = store
        self._pending: list[tuple[str, str]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(statement)
        params = params or {}
        if "INSERT INTO chat_stream_events" in sql:
            self._store.insert(params["cid"], params.get("payload", ""), "TRUE)" in sql)
            return _FakeResult()
        if "pg_notify" in sql:
            self._pending.append((params["channel"], params["payload"]))
            return _FakeResult()
        if sql.startswith("SELECT sequence"):
            rows = [
                event
                for event in self._store.events
                if event.conv_id == params["cid"] and event.sequence > params["last"]
            ]
            return _FakeResult(rows=rows)
        if "COALESCE" in sql:
            return _FakeResult(scalar=self._store.task_exists)
        return _FakeResult()

    async def commit(self) -> None:
        for channel, payload in self._pending:
            self._store.notifies.append((channel, payload))
            if self._store.deliver is not None:
                self._store.deliver(channel, payload)
        self._pending.clear()


class RegistryOnSharedBusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.bus = ChatStreamBus()
        self.connections: list[_FakeConnection] = []

        async def connect(_dsn: str, **_kwargs: Any) -> _FakeConnection:
            connection = _FakeConnection()
            self.connections.append(connection)
            return connection

        def deliver(channel: str, payload: str) -> None:
            for connection in self.connections:
                callback = connection.listeners.get(channel)
                if callback is not None and not connection.closed:
                    callback(connection, 1, channel, payload)

        self.store.deliver = deliver

        for patcher in (
            patch("app.services.chat_task_registry.async_session_maker", self._session),
            patch("app.services.chat_task_registry.chat_stream_bus", self.bus),
            patch("app.services.chat_stream_bus.asyncpg.connect", connect),
            # Notifications must wake subscribers; polling is pushed out of the way.
            patch("app.services.chat_task_registry._POLL_FALLBACK_CONNECTED_SECONDS", 60.0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addAsyncCleanup(self.bus.stop)

    def _session(self) -> _FakeSession:
        return _FakeSession(self.store)

    async def _next(self, queue: asyncio.Queue, timeout: float = 1.0) -> Any:
        return await asyncio.wait_for(queue.get(), timeout=timeout)

    async def test_publish_notifies_the_shared_channel_with_the_conversation_id(self) -> None:
        conv_id = str(uuid.uuid4())

        await registry.publish(conv_id, {"type": "chunk"})
        await registry.finish(conv_id)

        self.assertEqual([(CHANNEL, conv_id), (CHANNEL, conv_id)], self.store.notifies)

    async def test_published_event_reaches_the_subscriber_via_notification(self) -> None:
        conv_id = str(uuid.uuid4())

        async with registry.subscribe(conv_id) as queue:
            assert queue is not None
            await registry.publish(conv_id, {"type": "chunk", "text": "hi"})

            item = await self._next(queue)

        self.assertEqual('data: {"type": "chunk", "text": "hi"}\n\n', item)

    async def test_stream_ends_with_none_after_finish(self) -> None:
        conv_id = str(uuid.uuid4())

        async with registry.subscribe(conv_id) as queue:
            assert queue is not None
            await registry.publish(conv_id, "data: one\n\n")
            await registry.finish(conv_id)

            items = [await self._next(queue), await self._next(queue)]

        self.assertEqual(["data: one\n\n", None], items)

    async def test_late_subscriber_replays_what_it_missed(self) -> None:
        conv_id = str(uuid.uuid4())
        await registry.publish(conv_id, "data: early\n\n")
        await registry.finish(conv_id)

        async with registry.subscribe(conv_id) as queue:
            assert queue is not None
            items = [await self._next(queue), await self._next(queue)]

        self.assertEqual(["data: early\n\n", None], items)

    async def test_other_conversations_are_not_woken(self) -> None:
        mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())

        async with (
            registry.subscribe(mine) as my_queue,
            registry.subscribe(theirs) as their_queue,
        ):
            assert my_queue is not None and their_queue is not None
            await registry.publish(mine, "data: mine\n\n")

            self.assertEqual("data: mine\n\n", await self._next(my_queue))
            with self.assertRaises(TimeoutError):
                await self._next(their_queue, timeout=0.1)

    async def test_many_streams_share_a_single_database_connection(self) -> None:
        conv_ids = [str(uuid.uuid4()) for _ in range(25)]

        async with contextlib.AsyncExitStack() as stack:
            queues = [await stack.enter_async_context(registry.subscribe(c)) for c in conv_ids]
            self.assertTrue(all(queue is not None for queue in queues))
            self.assertEqual(25, self.bus.subscriber_count())
            self.assertEqual(1, len(self.connections))

            await registry.publish(conv_ids[7], "data: only-seven\n\n")
            self.assertEqual("data: only-seven\n\n", await self._next(queues[7]))

        self.assertEqual(1, len(self.connections))

    async def test_leaving_a_stream_releases_its_registration(self) -> None:
        conv_id = str(uuid.uuid4())

        async with registry.subscribe(conv_id) as queue:
            assert queue is not None
            self.assertEqual(1, self.bus.subscriber_count())

        self.assertEqual(0, self.bus.subscriber_count())
        self.assertFalse(self.connections[0].closed, "the shared connection must stay open")

    async def test_unknown_conversation_yields_no_queue_and_registers_nothing(self) -> None:
        self.store.task_exists = False

        async with registry.subscribe(str(uuid.uuid4())) as queue:
            self.assertIsNone(queue)

        self.assertEqual(0, self.bus.subscriber_count())


class RegistryPollingFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_still_arrive_when_the_listen_connection_is_down(self) -> None:
        store = _Store()
        bus = ChatStreamBus()

        async def connect(_dsn: str, **_kwargs: Any) -> _FakeConnection:
            raise OSError("connection refused")

        for patcher in (
            patch(
                "app.services.chat_task_registry.async_session_maker", lambda: _FakeSession(store)
            ),
            patch("app.services.chat_task_registry.chat_stream_bus", bus),
            patch("app.services.chat_stream_bus.asyncpg.connect", connect),
            patch("app.services.chat_stream_bus._RECONNECT_DELAY_SECONDS", 0.01),
            patch("app.services.chat_task_registry._LISTEN_READY_TIMEOUT_SECONDS", 0.05),
            patch("app.services.chat_task_registry._POLL_FALLBACK_DISCONNECTED_SECONDS", 0.05),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addAsyncCleanup(bus.stop)
        conv_id = str(uuid.uuid4())

        async with registry.subscribe(conv_id) as queue:
            assert queue is not None
            await registry.publish(conv_id, "data: polled\n\n")

            item = await asyncio.wait_for(queue.get(), timeout=2.0)

        self.assertEqual("data: polled\n\n", item)


async def _postgres_reachable() -> bool:
    try:
        connection = await asyncpg.connect(libpq_dsn(), timeout=3)
    except Exception:
        return False
    await connection.close()
    return True


class RealPostgresNotificationTests(unittest.IsolatedAsyncioTestCase):
    """LISTEN/NOTIFY through a real server; skipped when none is reachable."""

    async def asyncSetUp(self) -> None:
        if not await _postgres_reachable():
            self.skipTest("PostgreSQL is not reachable")
        self.bus = ChatStreamBus()
        self.addAsyncCleanup(self.bus.stop)
        self.sender = await asyncpg.connect(libpq_dsn())
        self.addAsyncCleanup(self.sender.close)

    async def _notify(self, conv_id: str) -> None:
        await self.sender.execute("SELECT pg_notify($1, $2)", CHANNEL, conv_id)

    async def test_notification_wakes_only_the_matching_subscriber(self) -> None:
        mine, theirs = asyncio.Event(), asyncio.Event()
        conv_id = str(uuid.uuid4())
        self.bus.register(conv_id, mine)
        self.bus.register(str(uuid.uuid4()), theirs)

        await self.bus.start()
        self.assertTrue(await self.bus.wait_until_listening(5.0))
        mine.clear()
        theirs.clear()
        await self._notify(conv_id)

        await asyncio.wait_for(mine.wait(), timeout=3.0)
        self.assertFalse(theirs.is_set())

    async def test_listener_is_replaced_after_the_server_kills_it(self) -> None:
        captured: list[asyncpg.Connection] = []
        real_connect = asyncpg.connect

        async def capturing_connect(*args: Any, **kwargs: Any) -> asyncpg.Connection:
            connection = await real_connect(*args, **kwargs)
            captured.append(connection)
            return connection

        conv_id = str(uuid.uuid4())
        event = asyncio.Event()
        self.bus.register(conv_id, event)

        with (
            patch("app.services.chat_stream_bus.asyncpg.connect", capturing_connect),
            patch("app.services.chat_stream_bus._RECONNECT_DELAY_SECONDS", 0.05),
            patch("app.services.chat_stream_bus._CONNECTION_PROBE_SECONDS", 0.05),
        ):
            await self.bus.start()
            self.assertTrue(await self.bus.wait_until_listening(5.0))
            victim_pid = captured[0].get_server_pid()

            await self.sender.execute("SELECT pg_terminate_backend($1)", victim_pid)
            for _ in range(200):
                if len(captured) >= 2 and self.bus.is_connected:
                    break
                await asyncio.sleep(0.05)
            self.assertGreaterEqual(len(captured), 2, "listener did not reconnect")

            event.clear()
            await self._notify(conv_id)
            await asyncio.wait_for(event.wait(), timeout=3.0)

    async def test_listener_connection_is_tagged_with_the_instance(self) -> None:
        await self.bus.start()
        self.assertTrue(await self.bus.wait_until_listening(5.0))
        tag = listener_server_settings()["application_name"]

        count = await self.sender.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE application_name = $1", tag
        )

        self.assertGreaterEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
