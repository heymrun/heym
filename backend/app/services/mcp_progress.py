"""`notifications/progress` for one MCP request.

The message says what the request is doing now: the Heym Agent's current step, or the
workflow node that is running. A timer repeats the latest message so clients that reset
their timeout on progress keep waiting; the counter grows with every notification, as the
MCP specification requires.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.execution_cancellation import get_active_execution_progress

DEFAULT_PROGRESS_MESSAGE = "Workflow is still running"
AGENT_PROGRESS_MESSAGE = "Heym Agent is working"


class MCPProgress:
    """Progress notifications for one request; a no-op when the client sent no token."""

    def __init__(
        self,
        token: str | int | None,
        send: Callable[[dict[str, Any]], Awaitable[None]] | None,
        *,
        message: str = DEFAULT_PROGRESS_MESSAGE,
    ) -> None:
        self._token = token
        self._send = send
        self._sequence = 0
        self.message = message
        # Asked for a fresh message on every timer tick when set, e.g. the running node.
        self.describe: Callable[[], str | None] | None = None

    async def report(self, message: str | None = None) -> None:
        """Send one notification: `message`, or the latest one refreshed by `describe`."""
        if message:
            self.message = message
        elif self.describe is not None:
            self.message = self.describe() or self.message
        if self._token is None or self._send is None:
            return
        await self._send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {
                    "progressToken": self._token,
                    "progress": self._sequence,
                    "message": self.message,
                },
            }
        )
        self._sequence += 1


def running_node_message(execution_id: uuid.UUID, workflow: Any) -> str | None:
    """`Running node <label>` for an execution on this instance, or None when unknown."""
    progress = get_active_execution_progress(execution_id, workflow_id=workflow.id)
    if progress is None:
        return None
    running_ids, _ = progress
    if not running_ids:
        return None
    labels: dict[str, str] = {}
    for node in workflow.nodes or []:
        if isinstance(node, dict) and node.get("id"):
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            labels[str(node["id"])] = str(data.get("label") or node["id"])
    names = [labels.get(node_id, node_id) for node_id in running_ids[:3]]
    return "Running node " + ", ".join(names)
