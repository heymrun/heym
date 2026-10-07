"""One shared LISTEN connection per process for dashboard chat stream wake-ups and cancel broadcasts.

Chat streams used to open a dedicated asyncpg connection per subscriber and
LISTEN on a channel named after the conversation. Every open stream therefore
held a database connection for its whole lifetime, so connection usage grew
with traffic instead of with the number of processes.

This bus replaces that with a single connection per process on a single
channel (``heym_chat_stream``). The payload of each notification is either:
  - the conversation id: wakes up in-process stream subscribers to read new events
    from the durable ``chat_stream_events`` table.
  - ``cancel:<conversation_id>`` or ``cancel:<conversation_id>:<run_id>``: dispatches
    a cancellation signal to whichever worker owns the running turn, and wakes
    subscribers so open client streams immediately read the cancelled state.

Subscribers and turn workers maintain a slow polling fallback for reconnection
windows where a notification might be missed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from typing import Any

import asyncpg

from app.db.session import libpq_dsn, listener_server_settings

logger = logging.getLogger(__name__)

CHANNEL = "heym_chat_stream"
_RECONNECT_DELAY_SECONDS = 2.0
# asyncpg surfaces a dead connection only on use; poke it so a socket that died
# quietly is noticed instead of leaving every stream in the process deaf.
_CONNECTION_PROBE_SECONDS = 15.0


def _key(conv_id: str) -> str:
    return str(conv_id).strip().lower()


CancelHandler = Callable[[uuid.UUID, uuid.UUID | None], Any]


class ChatStreamBus:
    """Fans a conversation-id notification out to the subscribers in this process."""

    def __init__(self) -> None:
        self._waiters: dict[str, set[asyncio.Event]] = {}
        self._cancel_handlers: list[CancelHandler] = []
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Event | None = None
        self._running = False
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def subscriber_count(self) -> int:
        return sum(len(events) for events in self._waiters.values())

    def register(self, conv_id: str, event: asyncio.Event) -> None:
        """Wake ``event`` whenever a notification names ``conv_id``."""
        self._waiters.setdefault(_key(conv_id), set()).add(event)

    def unregister(self, conv_id: str, event: asyncio.Event) -> None:
        key = _key(conv_id)
        events = self._waiters.get(key)
        if events is None:
            return
        events.discard(event)
        if not events:
            self._waiters.pop(key, None)

    def register_cancel_handler(self, handler: CancelHandler) -> None:
        """Register a callback for cross-worker cancellation notifications."""
        if handler not in self._cancel_handlers:
            self._cancel_handlers.append(handler)

    def unregister_cancel_handler(self, handler: CancelHandler) -> None:
        """Unregister a previously registered cancellation callback."""
        if handler in self._cancel_handlers:
            self._cancel_handlers.remove(handler)

    def handle_payload(self, payload: str) -> int:
        """Handle an incoming notification payload.

        If payload starts with "cancel:", it is parsed as a cancel broadcast
        (format: "cancel:<conversation_id>" or "cancel:<conversation_id>:<run_id>"),
        validated, dispatched to registered cancel callbacks, and wakes up any
        subscribers for that conversation.

        Otherwise, the payload is treated as a conversation id and wakes up
        subscribers for that conversation.

        Returns how many subscriber events woke up.
        """
        payload_str = str(payload).strip()
        if payload_str.startswith("cancel:"):
            body = payload_str[len("cancel:") :].strip()
            parts = body.split(":")
            conv_id_raw = parts[0].strip() if parts else ""
            run_id_raw = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

            try:
                conv_uuid = uuid.UUID(conv_id_raw)
            except (ValueError, AttributeError):
                logger.warning(
                    "Ignoring chat cancel notification with invalid conversation UUID: %r", payload
                )
                return 0

            run_uuid: uuid.UUID | None = None
            if run_id_raw:
                try:
                    run_uuid = uuid.UUID(run_id_raw)
                except (ValueError, AttributeError):
                    logger.warning(
                        "Ignoring chat cancel notification with invalid run UUID: %r", payload
                    )
                    return 0

            for handler in list(self._cancel_handlers):
                try:
                    handler(conv_uuid, run_uuid)
                except Exception:
                    logger.exception("Chat cancel handler failed for payload %r", payload)

            events = self._waiters.get(_key(str(conv_uuid)))
            if not events:
                return 0
            for event in tuple(events):
                event.set()
            return len(events)

        events = self._waiters.get(_key(payload_str))
        if not events:
            return 0
        for event in tuple(events):
            event.set()
        return len(events)

    def wake_all(self) -> None:
        """Wake every subscriber so each one re-reads its events.

        Called after a (re)connect: notifications sent while the connection was
        down are gone, but the events they announced are in the table.
        """
        for events in tuple(self._waiters.values()):
            for event in tuple(events):
                event.set()

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            self.handle_payload(payload)
        except Exception:
            logger.exception("Chat stream notification handling failed")

    async def start(self) -> None:
        """Start the listen loop on the running event loop. Safe to call repeatedly."""
        loop = asyncio.get_running_loop()
        if self._task is not None and not self._task.done() and self._loop is loop:
            return
        # A task bound to another (for example closed) loop can never make progress.
        self._running = True
        self._loop = loop
        self._ready = asyncio.Event()
        self._connected = False
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("Chat stream listener started (channel=%s)", CHANNEL)

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await task
        self._connected = False
        self._loop = None
        self._ready = None

    async def wait_until_listening(self, timeout: float) -> bool:
        """Wait for the first LISTEN to be in place; False if it did not happen in time.

        A subscriber that registers before LISTEN is active would only learn
        about early events from its polling fallback, so it waits briefly
        first. Failing to connect is not fatal - polling still delivers.
        """
        ready = self._ready
        if ready is None:
            return False
        if ready.is_set():
            return True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(ready.wait(), timeout=timeout)
        return ready.is_set()

    async def _listen_loop(self) -> None:
        while self._running:
            connection: asyncpg.Connection | None = None
            try:
                connection = await asyncpg.connect(
                    libpq_dsn(), server_settings=listener_server_settings()
                )
                await connection.add_listener(CHANNEL, self._on_notify)
                self._connected = True
                if self._ready is not None:
                    self._ready.set()
                self.wake_all()
                while self._running:
                    await asyncio.sleep(_CONNECTION_PROBE_SECONDS)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Chat stream listener disconnected (%s); retrying in %.0fs",
                    exc,
                    _RECONNECT_DELAY_SECONDS,
                )
            finally:
                self._connected = False
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


chat_stream_bus = ChatStreamBus()
