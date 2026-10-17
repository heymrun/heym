"""What a trigger diff produces: run payloads plus the snapshot writes that consume them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: A sheet row whose key moved to another row number: the snapshot follows it, no run starts.
MOVED = "moved"


@dataclass(frozen=True)
class ItemWrite:
    """Set one stored item to ``payload``, or remove it when ``payload`` is None."""

    item_key: str
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class TriggerEvent:
    """One change: what the run receives, the write that consumes it, the write that undoes it."""

    event: str
    payload: dict[str, Any]
    write: ItemWrite
    revert: ItemWrite


class PollSkippedError(Exception):
    """The poll cannot produce a trustworthy snapshot; the stored one must stay as it is."""
