"""Postgres-backed broadcast registry for background dashboard chat streams.

The previous implementation kept conversation streams in a per-process dict,
which broke under `uvicorn --workers N` (the POST that started the task and the
GET that subscribed to it could land on different workers). This implementation
uses a `chat_stream_events` table for durable replay plus Postgres
`LISTEN`/`NOTIFY` to wake up subscribers in any worker. Every process holds a
single shared LISTEN connection (see `chat_stream_bus`) instead of one per
stream, so open streams do not consume database connections.

Wire-format compatibility: events are serialized to SSE-formatted strings at
publish time, so consumers receive `str` payloads (already `data: ...\\n\\n`)
or `None` to signal stream completion.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa

from app.db.session import async_session_maker
from app.services.chat_stream_bus import CHANNEL as CHAT_STREAM_CHANNEL
from app.services.chat_stream_bus import chat_stream_bus

ChatEvent = str | dict[str, Any]
logger = logging.getLogger(__name__)

# How long a subscriber waits for the shared LISTEN to be established before it
# falls back to polling alone.
_LISTEN_READY_TIMEOUT_SECONDS = 2.0
# A notification only wakes a subscriber early; the events are read from the
# table. The fallback covers a notification lost while the shared connection was
# down, or sent by a process still running the previous per-conversation channel.
_POLL_FALLBACK_CONNECTED_SECONDS = 10.0
_POLL_FALLBACK_DISCONNECTED_SECONDS = 2.0


async def _notify(session: Any, conv_id: str) -> None:
    """Announce new events for ``conv_id``. Delivered when the transaction commits."""
    await session.execute(
        sa.text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHAT_STREAM_CHANNEL, "payload": conv_id},
    )


async def publish_cancel(
    session: Any,
    conv_id: Any,
    run_id: Any = None,
) -> None:
    """Announce a cancellation signal across workers for ``conv_id``."""
    payload = f"cancel:{conv_id}:{run_id}" if run_id is not None else f"cancel:{conv_id}"
    await session.execute(
        sa.text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHAT_STREAM_CHANNEL, "payload": payload},
    )


def _serialize_event(event: ChatEvent) -> str:
    if isinstance(event, str):
        return event
    return f"data: {json.dumps(event)}\n\n"


async def create_task(conv_id: str) -> None:
    """Wipe any previous events for this conversation; start a fresh slot.

    Bounds per-conversation storage to at most one stream's worth of events.
    """
    async with async_session_maker() as session:
        await session.execute(
            sa.text("DELETE FROM chat_stream_events WHERE conversation_id = CAST(:cid AS uuid)"),
            {"cid": conv_id},
        )
        await session.commit()


async def has_task(conv_id: str) -> bool:
    """Return True if a chat task is currently active for this conversation.

    "Active" means either:
      - the conversation row's `is_running` flag is true (a task was just
        created and may not have published its first event yet), or
      - there are still events in the stream table that no consumer has
        observed and acknowledged (we don't delete on consume, so this is
        any rows at all).
    """
    async with async_session_maker() as session:
        result = await session.execute(
            sa.text(
                "SELECT "
                "  COALESCE((SELECT is_running FROM dashboard_conversations "
                "            WHERE id = CAST(:cid AS uuid)), FALSE) "
                "  OR EXISTS (SELECT 1 FROM chat_stream_events "
                "             WHERE conversation_id = CAST(:cid AS uuid))"
            ),
            {"cid": conv_id},
        )
        return bool(result.scalar())


async def remove_task(conv_id: str) -> None:
    async with async_session_maker() as session:
        await session.execute(
            sa.text("DELETE FROM chat_stream_events WHERE conversation_id = CAST(:cid AS uuid)"),
            {"cid": conv_id},
        )
        await session.commit()


async def publish(conv_id: str, event: ChatEvent) -> None:
    payload = _serialize_event(event)
    async with async_session_maker() as session:
        await session.execute(
            sa.text(
                "INSERT INTO chat_stream_events (conversation_id, payload, is_done) "
                "VALUES (CAST(:cid AS uuid), :payload, FALSE)"
            ),
            {"cid": conv_id, "payload": payload},
        )
        await _notify(session, conv_id)
        await session.commit()


async def finish(conv_id: str) -> None:
    async with async_session_maker() as session:
        await session.execute(
            sa.text(
                "INSERT INTO chat_stream_events (conversation_id, payload, is_done) "
                "VALUES (CAST(:cid AS uuid), '', TRUE)"
            ),
            {"cid": conv_id},
        )
        await _notify(session, conv_id)
        await session.commit()


async def subscriber_count(conv_id: str) -> int:
    """Not tracked across workers under the Postgres-backed registry.

    Callers used this to set `has_unread = (count == 0)`; we now always mark
    such conversations as unread on finish, and rely on the frontend's
    markConversationRead path to clear it when the user views the chat.
    """
    return 0


@asynccontextmanager
async def subscribe(
    conv_id: str,
) -> AsyncGenerator[asyncio.Queue[ChatEvent | None] | None, None]:
    """Subscribe to a conversation stream.

    Yields a `Queue[str | None]` that emits SSE-formatted strings and a final
    `None` to signal completion. Yields `None` (instead of a queue) when no
    task ever existed for this conversation, matching the previous semantics.
    """
    if not await has_task(conv_id):
        yield None
        return

    queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
    listener_task: asyncio.Task[None] | None = None
    last_seq = 0
    notify_wakeup = asyncio.Event()

    async def fetch_new_events() -> bool:
        """Push newly-arrived events to the queue. Return True after `done`."""
        nonlocal last_seq
        async with async_session_maker() as session:
            result = await session.execute(
                sa.text(
                    "SELECT sequence, payload, is_done FROM chat_stream_events "
                    "WHERE conversation_id = CAST(:cid AS uuid) AND sequence > :last "
                    "ORDER BY sequence"
                ),
                {"cid": conv_id, "last": last_seq},
            )
            rows = result.all()
        saw_done = False
        for row in rows:
            last_seq = row.sequence
            if row.is_done:
                await queue.put(None)
                saw_done = True
            else:
                await queue.put(row.payload)
        return saw_done

    async def listener() -> None:
        try:
            while True:
                poll_after = (
                    _POLL_FALLBACK_CONNECTED_SECONDS
                    if chat_stream_bus.is_connected
                    else _POLL_FALLBACK_DISCONNECTED_SECONDS
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(notify_wakeup.wait(), timeout=poll_after)
                notify_wakeup.clear()
                if await fetch_new_events():
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat stream listener crashed for conv_id=%s", conv_id)
            with contextlib.suppress(Exception):
                await queue.put(None)

    await chat_stream_bus.start()
    await chat_stream_bus.wait_until_listening(_LISTEN_READY_TIMEOUT_SECONDS)
    # Register before the first drain so a notification that lands in between
    # is not lost; the shared connection is already listening at this point.
    chat_stream_bus.register(conv_id, notify_wakeup)

    try:
        # Drain whatever already exists before yielding the queue so the consumer
        # never misses early events that arrived before the registration.
        if await fetch_new_events():
            yield queue
            return
        # Schedule another drain in case a NOTIFY fired between the initial
        # fetch and registration — set the wakeup so the listener picks it up.
        notify_wakeup.set()
        listener_task = asyncio.create_task(listener())
        yield queue
    finally:
        chat_stream_bus.unregister(conv_id, notify_wakeup)
        if listener_task is not None:
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task
