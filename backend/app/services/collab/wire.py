"""Wire format for canvas collaboration messages on the ``heym_collab`` NOTIFY channel.

A NOTIFY payload holds at most 8000 bytes. A message that encodes larger is split into
chunks that ``bus.py`` sends inside one transaction. Postgres queues one transaction's
notifications contiguously, so a listener sees the chunks of a message back to back and in
order. Each payload is ``<room>|<msg_id>|<index>/<count>|<chunk>``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

CHANNEL = "heym_collab"
MAX_CHUNK_BYTES = 7000
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
PARTIAL_TTL_SECONDS = 10.0


class MessageTooLargeError(ValueError):
    """Raised when an encoded message exceeds ``MAX_MESSAGE_BYTES``."""


@dataclass(frozen=True)
class WirePayload:
    """One NOTIFY payload, parsed."""

    room: str
    msg_id: str
    index: int
    count: int
    chunk: str


def split_chunks(text: str, limit: int = MAX_CHUNK_BYTES) -> list[str]:
    """Split ``text`` into pieces of at most ``limit`` UTF-8 bytes, on character boundaries."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(data):
        end = min(start + limit, len(data))
        while end < len(data) and (data[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(data[start:end].decode("utf-8"))
        start = end
    return chunks


def encode_payloads(room: str, text: str, msg_id: str | None = None) -> list[str]:
    """Return the NOTIFY payloads that carry ``text`` to ``room``."""
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise MessageTooLargeError("collab message exceeds the size limit")
    message_id = msg_id or uuid.uuid4().hex
    chunks = split_chunks(text)
    count = len(chunks)
    return [f"{room}|{message_id}|{index}/{count}|{chunk}" for index, chunk in enumerate(chunks)]


def parse_payload(payload: str) -> WirePayload | None:
    """Parse one NOTIFY payload; None when it is malformed."""
    parts = payload.split("|", 3)
    if len(parts) != 4:
        return None
    room, msg_id, position, chunk = parts
    index_text, _, count_text = position.partition("/")
    if not index_text.isdigit() or not count_text.isdigit():
        return None
    index, count = int(index_text), int(count_text)
    if count < 1 or index >= count:
        return None
    return WirePayload(room=room, msg_id=msg_id, index=index, count=count, chunk=chunk)


@dataclass
class _Partial:
    started_at: float
    count: int
    parts: list[str] = field(default_factory=list)


class ChunkAssembler:
    """Reassembles chunked messages and drops one whose chunks stop arriving."""

    def __init__(self, ttl_seconds: float = PARTIAL_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._partials: dict[str, _Partial] = {}

    def pending_count(self) -> int:
        """How many messages are waiting for more chunks."""
        return len(self._partials)

    def feed(self, payload: WirePayload, now: float) -> str | None:
        """Add one chunk; return the whole message once its last chunk arrives."""
        self._prune(now)
        if payload.count == 1:
            return payload.chunk
        partial = self._partials.get(payload.msg_id)
        if partial is None:
            if payload.index != 0:
                return None
            partial = _Partial(started_at=now, count=payload.count)
            self._partials[payload.msg_id] = partial
        if payload.count != partial.count or payload.index != len(partial.parts):
            self._partials.pop(payload.msg_id, None)
            return None
        partial.parts.append(payload.chunk)
        if len(partial.parts) < partial.count:
            return None
        self._partials.pop(payload.msg_id, None)
        return "".join(partial.parts)

    def _prune(self, now: float) -> None:
        expired = [key for key, item in self._partials.items() if now - item.started_at > self._ttl]
        for key in expired:
            self._partials.pop(key, None)
