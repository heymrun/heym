"""Keep long-running JSON operations alive across HTTP proxies."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15.0
_RUNNING: set[asyncio.Task[Any]] = set()


async def _result(operation: Awaitable[Any]) -> dict[str, Any]:
    try:
        return {"type": "result", "result": jsonable_encoder(await operation)}
    except HTTPException as exc:
        return {"type": "error", "status": exc.status_code, "detail": exc.detail}
    except Exception:
        logger.exception("Streamed operation failed")
        return {"type": "error", "status": 500, "detail": "The run could not complete."}


async def result_events(task: asyncio.Task[dict[str, Any]]) -> AsyncIterator[str]:
    """Send immediately, then heartbeat until the independently owned run finishes."""
    yield ": heartbeat\n\n"
    while not task.done():
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
        if not done:
            yield ": heartbeat\n\n"
    yield f"data: {json.dumps(task.result())}\n\n"


def stream_result(operation: Awaitable[Any]) -> StreamingResponse:
    """Stream a result without cancelling its work when the listener disconnects."""
    task = asyncio.create_task(_result(operation))
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return StreamingResponse(
        result_events(task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
