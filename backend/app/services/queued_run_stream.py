"""The SSE stream of a run that is waiting for a concurrency slot.

The run executes in the run queue worker, possibly in another process, so this stream
only watches it: queue updates while held, ``execution_started`` once claimed, and one
``execution_complete`` from the status body at the end. Node events and token deltas
are not streamed for a queued run. A disconnect stops watching; the run still executes.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.services import workflow_concurrency

POLL_SECONDS = 2.0
HEARTBEAT = ": heartbeat\n\n"
TERMINAL_STATUSES = frozenset({"success", "error", "pending", "cancelled", "expired"})


def _frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def queued_run_events(
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    is_disconnected: Callable[[], Awaitable[bool]],
    simple_response: bool = False,
) -> AsyncIterator[str]:
    """Yield SSE frames for one held run until it ends or the client leaves."""
    last_queue: dict[str, Any] | None = None
    started = False
    while True:
        body = await workflow_concurrency.build_status_body(workflow_id, execution_id)
        if body is None:
            yield _frame(
                {
                    "type": "execution_complete",
                    "workflow_id": str(workflow_id),
                    "status": "error",
                    "outputs": {"error": "Execution not found"},
                    "node_results": [],
                    "execution_time_ms": 0.0,
                    "execution_history_id": None,
                }
            )
            return
        status = body.get("status")
        if status == "queued":
            queue = body.get("queue")
            if queue != last_queue:
                last_queue = queue
                yield _frame({"type": "queued", "execution_id": str(execution_id), **(queue or {})})
        elif status == "running" and not started:
            started = True
            yield _frame({"type": "execution_started", "execution_id": str(execution_id)})
        elif status in TERMINAL_STATUSES:
            if simple_response:
                yield _frame({"outputs": body.get("outputs") or {}})
            else:
                # Node results stay in the history row; they are not sent to an SSE caller.
                yield _frame(
                    {
                        "type": "execution_complete",
                        "workflow_id": str(workflow_id),
                        "status": status,
                        "outputs": body.get("outputs") or {},
                        "node_results": [],
                        "execution_time_ms": body.get("execution_time_ms") or 0.0,
                        "execution_history_id": str(execution_id),
                    }
                )
            return
        if await is_disconnected():
            return
        await asyncio.sleep(POLL_SECONDS)
        yield HEARTBEAT
