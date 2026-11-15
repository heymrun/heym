"""Start fire-and-forget tasks without letting the garbage collector drop them.

asyncio keeps only weak references to the tasks it runs. A task that nothing else
references can be collected while it is still suspended, which ends the work
silently ("Task was destroyed but it is pending"). Keep a strong reference until
the task is done.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def spawn_background_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Run ``coro`` in the background and keep it alive until it finishes."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task
