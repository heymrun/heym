"""Wait for a run that another instance is executing.

Every offloaded trigger needs its result back: Telegram, Slack and Discord reply
with it, MCP returns it as the tool output, and the execute endpoint returns it
as the HTTP response. The executing instance notifies `heym_run_done` with the
execution id; this module turns that into a per-execution asyncio.Event so a
waiting request wakes immediately instead of polling tightly.

One listener per process serves every waiter. Polling still runs as a fallback,
so a dropped listener costs latency rather than correctness.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import asyncpg

from app.db.session import libpq_dsn

logger = logging.getLogger("cluster")

CHANNEL = "heym_run_done"
POLL_INTERVAL_SECONDS = 1.0
# A waiter must not outlive a worker that died mid-run. Orphan recovery will
# re-run the execution; the caller is told the result is not available yet.
DEFAULT_WAIT_SECONDS = 900.0
_RECONNECT_DELAY_SECONDS = 2.0
_CONNECTION_PROBE_SECONDS = 15.0


class RunResultBus:
    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Event] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def register(self, execution_id: uuid.UUID) -> asyncio.Event:
        """Start listening for one execution before it is enqueued.

        Registering first is what makes the notify race safe: a run that
        finishes before the caller starts waiting still sets the event.
        """
        event = asyncio.Event()
        self._waiters[str(execution_id)] = event
        return event

    def release(self, execution_id: uuid.UUID) -> None:
        self._waiters.pop(str(execution_id), None)

    def handle_payload(self, payload: str) -> bool:
        """Wake the waiter for this execution. True when one was waiting here."""
        event = self._waiters.get(payload.strip())
        if event is None:
            return False
        event.set()
        return True

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            self.handle_payload(payload)
        except Exception:
            logger.exception("Run result notification handling failed")

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("Run result listener started (channel=%s)", CHANNEL)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _listen_loop(self) -> None:
        while self._running:
            connection: asyncpg.Connection | None = None
            try:
                connection = await asyncpg.connect(libpq_dsn())
                await connection.add_listener(CHANNEL, self._on_notify)
                while self._running:
                    await asyncio.sleep(_CONNECTION_PROBE_SECONDS)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Run result listener disconnected (%s); retrying in %.0fs",
                    exc,
                    _RECONNECT_DELAY_SECONDS,
                )
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


run_result_bus = RunResultBus()
