"""Wake this instance when a run is enqueued for it.

Mirrors execution_cancel_bus.py: a dedicated asyncpg LISTEN connection turns a
pg_notify into an in-process event, so the claim loop does not have to poll
tightly. Polling still runs as a slow fallback, so a dropped LISTEN connection
degrades latency rather than stalling the queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import asyncpg

from app.db.session import libpq_dsn

logger = logging.getLogger("cluster")

CHANNEL = "heym_run_queue"
POLL_FALLBACK_SECONDS = 5.0
_RECONNECT_DELAY_SECONDS = 2.0
_CONNECTION_PROBE_SECONDS = 15.0


def is_for_me(payload: str, *, instance_id: str) -> bool:
    return payload.strip() == instance_id


class QueueWakeBus:
    def __init__(self, instance_id: str) -> None:
        self._instance_id = instance_id
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def has_pending_wake(self) -> bool:
        return self._wake.is_set()

    def handle_payload(self, payload: str) -> bool:
        """Set the wake flag when the payload names this instance."""
        if not is_for_me(payload, instance_id=self._instance_id):
            return False
        self._wake.set()
        return True

    async def wait_for_work(self) -> None:
        """Block until notified, or until the fallback poll interval elapses.

        The flag is checked before waiting, so a notify that lands between two
        claim passes is never lost.
        """
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=POLL_FALLBACK_SECONDS)
        self._wake.clear()

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            self.handle_payload(payload)
        except Exception:
            logger.exception("Queue wake payload handling failed")

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("Queue wake listener started (channel=%s)", CHANNEL)

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
                    "Queue wake listener disconnected (%s); retrying in %.0fs",
                    exc,
                    _RECONNECT_DELAY_SECONDS,
                )
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
