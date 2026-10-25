"""One LISTEN and one publish connection per process for canvas collaboration.

Mirrors ``chat_stream_bus.py``. Every collab frame is published with ``pg_notify`` on
``heym_collab`` and comes back to every process in Postgres commit order, so every canvas sees
one order of edits. Both connections open lazily when the first collab socket in the process
needs them; an instance nobody collaborates on holds no extra connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

from app.db.session import libpq_dsn, listener_server_settings
from app.services.collab.hub import CollabHub, collab_hub
from app.services.collab.protocol import RoutedMessage
from app.services.collab.wire import CHANNEL, ChunkAssembler, encode_payloads, parse_payload

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 2.0
# asyncpg notices a dead socket only on use; probe it so a silent drop is noticed.
_CONNECTION_PROBE_SECONDS = 15.0

Connect = Callable[[], Awaitable[Any]]


class CollabPublishError(RuntimeError):
    """Publishing failed; the publish connection is reopened on the next attempt."""


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(libpq_dsn(), server_settings=listener_server_settings())


class CollabBus:
    """Publishes collab frames and hands every received one to the local hub."""

    def __init__(self, hub: CollabHub, connect: Connect = _connect) -> None:
        self._hub = hub
        self._connect = connect
        self._assembler = ChunkAssembler()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Event | None = None
        self._running = False
        self._publisher: Any = None
        self._publish_lock: asyncio.Lock | None = None

    async def ensure_started(self, timeout: float = 2.0) -> bool:
        """Start listening if this process is not yet; True once LISTEN is in place."""
        loop = asyncio.get_running_loop()
        if self._task is None or self._task.done() or self._loop is not loop:
            self._running = True
            self._loop = loop
            self._ready = asyncio.Event()
            self._publish_lock = None
            self._publisher = None
            self._task = asyncio.create_task(self._listen_loop())
        ready = self._ready
        if ready is None:
            return False
        if not ready.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(ready.wait(), timeout=timeout)
        return ready.is_set()

    async def publish(self, room: str, message: RoutedMessage) -> None:
        """Publish one frame to ``room`` on every process.

        Raises ``MessageTooLargeError`` for an oversized frame and ``CollabPublishError`` when
        Postgres could not take it.
        """
        payloads = encode_payloads(room, message.to_wire())
        async with self._lock():
            try:
                connection = await self._publisher_connection()
                if len(payloads) == 1:
                    await connection.execute("SELECT pg_notify($1, $2)", CHANNEL, payloads[0])
                    return
                async with connection.transaction():
                    for payload in payloads:
                        await connection.execute("SELECT pg_notify($1, $2)", CHANNEL, payload)
            except Exception as exc:
                await self._drop_publisher()
                raise CollabPublishError("collab publish failed") from exc

    def handle_payload(self, payload: str, now: float | None = None) -> int:
        """Route one notification to local sockets. Returns how many sockets got a frame."""
        parsed = parse_payload(payload)
        if parsed is None or not self._hub.has_room(parsed.room):
            return 0
        text = self._assembler.feed(parsed, time.monotonic() if now is None else now)
        if text is None:
            return 0
        return self._hub.deliver(parsed.room, text)

    async def stop(self) -> None:
        """Stop listening and close both connections."""
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await task
        await self._drop_publisher()
        self._ready = None
        self._loop = None
        self._publish_lock = None

    def _lock(self) -> asyncio.Lock:
        if self._publish_lock is None:
            self._publish_lock = asyncio.Lock()
        return self._publish_lock

    async def _publisher_connection(self) -> Any:
        if self._publisher is None or self._publisher.is_closed():
            self._publisher = await self._connect()
        return self._publisher

    async def _drop_publisher(self) -> None:
        publisher, self._publisher = self._publisher, None
        if publisher is not None:
            with contextlib.suppress(Exception):
                await publisher.close()

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            self.handle_payload(payload)
        except Exception:
            logger.exception("Collab notification handling failed")

    async def _listen_loop(self) -> None:
        while self._running:
            connection: Any = None
            try:
                connection = await self._connect()
                await connection.add_listener(CHANNEL, self._on_notify)
                if self._ready is not None:
                    self._ready.set()
                # Frames sent while no LISTEN was in place are gone; let every canvas catch up.
                self._hub.broadcast_resync()
                while self._running:
                    await asyncio.sleep(_CONNECTION_PROBE_SECONDS)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Collab listener disconnected (%s); retrying in %.0fs",
                    exc,
                    _RECONNECT_DELAY_SECONDS,
                )
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


collab_bus = CollabBus(collab_hub)
