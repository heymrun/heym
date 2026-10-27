"""What the Heym Agent is doing right now, one short sentence per step.

The chat engine already labels every tool step for the Chat tab: each `tool_start` event
carries a `label` such as `Running workflow "Invoice Parser"...`. Progress reuses those
labels, so the Chat tab, MCP clients and A2A clients describe a step the same way, and a
new chat tool is described the moment it gets its Chat tab label.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentProgress:
    step: int
    message: str


ProgressCallback = Callable[[AgentProgress], Awaitable[None]]


def step_message(payload: dict[str, Any]) -> str | None:
    """The sentence for one chat stream event, or None when the event does not start a step."""
    if payload.get("type") != "tool_start":
        return None
    label = " ".join(str(payload.get("label") or "").split()).rstrip(".").strip()
    if label:
        return label
    name = str(payload.get("name") or "").strip()
    return f"Using {name}" if name else "Working"


class TurnProgress:
    """Turns one turn's chat stream events into numbered progress steps."""

    def __init__(self, on_progress: ProgressCallback) -> None:
        self._on_progress = on_progress
        self._step = 0

    async def observe(self, payload: dict[str, Any]) -> None:
        message = step_message(payload)
        if message is None:
            return
        self._step += 1
        await self._on_progress(AgentProgress(step=self._step, message=message))
