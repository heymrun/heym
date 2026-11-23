"""The application's event loop, reachable from workflow executor threads.

Node handlers are synchronous and run in executor threads. Work that belongs to the
application loop, such as a Heym Chat turn, cannot run in a fresh ``asyncio.run`` loop
there: the async engine's pooled asyncpg connections, the chat task map and the chat
stream bus all belong to the loop the app started on. ``submit`` hands a coroutine to
that loop instead.

This module also carries the chat hop depth. A Heym node can send a chat message, and a
chat turn can run a workflow; ``chat_turn_depth`` counts those hops so the loop stops.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
from collections.abc import Coroutine, Iterator
from typing import Any, TypeVar

T = TypeVar("T")

_app_loop: asyncio.AbstractEventLoop | None = None

# How many Heym-node chat hops led to the code running now. A chat turn a Heym node
# started runs at depth 1; a workflow that turn runs reads 1 when its executor is built.
_chat_turn_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "heym_chat_turn_depth", default=0
)


def set_app_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Register the loop the application runs on. Called once from the lifespan."""
    global _app_loop
    _app_loop = loop


def get_app_loop() -> asyncio.AbstractEventLoop | None:
    """The registered application loop, or None outside a running app."""
    loop = _app_loop
    if loop is None or loop.is_closed():
        return None
    return loop


def submit(coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
    """Run ``coro`` on the application loop from another thread.

    Raises ``RuntimeError`` when no application loop is running, and when called from
    the loop's own thread, where waiting on the returned future would deadlock.
    """
    loop = get_app_loop()
    if loop is None or not loop.is_running():
        coro.close()
        raise RuntimeError("The Heym application loop is not running.")
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        coro.close()
        raise RuntimeError("submit() cannot be called from the application loop itself.")
    return asyncio.run_coroutine_threadsafe(coro, loop)


def chat_turn_depth() -> int:
    """The chat hop depth of the current context."""
    return _chat_turn_depth.get()


@contextlib.contextmanager
def chat_turn_depth_scope(depth: int) -> Iterator[None]:
    """Set the chat hop depth for the code inside, and for tasks it creates."""
    token = _chat_turn_depth.set(depth)
    try:
        yield
    finally:
        _chat_turn_depth.reset(token)
