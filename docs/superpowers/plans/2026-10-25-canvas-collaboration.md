# Canvas Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** People on the same workflow canvas see each other (avatars, cursors), edit one shared draft live, follow each other's view, and talk peer to peer.

**Architecture:** One WebSocket per open canvas (`WS /api/workflows/{id}/collab`). Every frame is validated, stamped with the sender's identity and published through Postgres `pg_notify` on `heym_collab`; a per-process LISTEN connection hands it to the local sockets of that room, so every browser sees one total order. Live editing is Figma-style per-key last-writer-wins on top of that order. Voice is browser WebRTC P2P with two public STUN servers and no TURN; signalling rides the same socket.

**Tech Stack:** FastAPI WebSocket, asyncpg LISTEN/NOTIFY, SQLAlchemy async, Vue 3 + Pinia + Vue Flow 1.48, `@vueuse/core`, browser WebSocket and WebRTC. No new packages.

**Spec:** `docs/superpowers/specs/2026-10-25-canvas-collaboration-design.md`

**Standing rules for this repo (override the skill defaults):**
- Do **not** commit, branch or push. Every task ends with the work left as a local diff.
- No frontend UI/component tests. Pure-logic Vitest specs (`src/**/*.test.ts`) are fine.
- Code, comments and docs in English. No em dashes in docs or user-facing copy.
- Backend test commands need `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false` when the shell does not export them.

---

## File map

Backend (new):
- `backend/app/services/collab/__init__.py`: package marker.
- `backend/app/services/collab/wire.py`: NOTIFY payload format, chunking, reassembly.
- `backend/app/services/collab/protocol.py`: identity, message routing rules, rate limiter, header parsers.
- `backend/app/services/collab/hub.py`: process-local sockets per room.
- `backend/app/services/collab/bus.py`: LISTEN + publish connections.
- `backend/app/services/collab/saves.py`: queue the `saved` notification inside a save transaction.
- `backend/app/api/collab.py`: the WebSocket endpoint.

Backend (modified): `app/api/deps.py`, `app/main.py`, `app/api/workflows.py`, `app/api/chat_build.py`.

Backend tests (new): `tests/test_canvas_collab_wire.py`, `tests/test_canvas_collab_protocol.py`, `tests/test_canvas_collab_hub.py`, `tests/test_canvas_collab_bus.py`, `tests/test_canvas_collab_socket.py`, `tests/test_canvas_collab_saves.py`. Modified: `tests/test_chat_build_session.py`.

Frontend (new, all under `frontend/src/features/collab/`):
- `types.ts`, `colors.ts`, `liveSync.ts` (pure), `collabClient.ts`, `followSignals.ts`
- `usePresence.ts`, `useLiveSync.ts`, `useFollow.ts`, `useVoice.ts`, `useCanvasCollab.ts`, `useEditorFollowSignals.ts`
- `CollabCanvasBridge.ts` (renderless Vue Flow child)
- `components/CollabOverlay.vue`, `components/CollabCursors.vue`, `components/FollowFrame.vue`
- Tests: `colors.test.ts`, `liveSync.test.ts`

Frontend (modified): `stores/workflow.ts`, `services/api.ts`, `views/EditorView.vue`, `components/Canvas/WorkflowCanvas.vue`, `components/ui/ExpressionInput.vue`, `components/Panels/DebugPanel.vue`, `components/Panels/ExecutionHistoryDialog.vue`, `components/Dialogs/WebPortalSettingsDialog.vue`.

Release tour, docs, README: `features/release-tour/*`, `docs/content/reference/*`, `docs/manifest.ts`, `README.md`, `docs/readme-assets/full-feature-showcase.svg`.

---

### Task 1: Wire format (chunking and reassembly)

**Files:**
- Create: `backend/app/services/collab/__init__.py`
- Create: `backend/app/services/collab/wire.py`
- Test: `backend/tests/test_canvas_collab_wire.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_canvas_collab_wire.py`:

```python
"""NOTIFY payloads for canvas collaboration: chunking, parsing and reassembly."""

import unittest

from app.services.collab.wire import (
    MAX_CHUNK_BYTES,
    ChunkAssembler,
    MessageTooLargeError,
    WirePayload,
    encode_payloads,
    parse_payload,
    split_chunks,
)

ROOM = "0b6f3d1e-2a4c-4f53-9a51-1d6c1b0f7e10"


def _parsed(payload: str) -> WirePayload:
    parsed = parse_payload(payload)
    if parsed is None:
        raise AssertionError(f"unparsable payload: {payload[:60]}")
    return parsed


class SplitChunksTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self) -> None:
        self.assertEqual(["hello"], split_chunks("hello"))

    def test_chunks_stay_under_the_byte_limit_without_splitting_characters(self) -> None:
        text = "é" * 5000 + "😀" * 3000 + "a" * 10

        chunks = split_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.encode("utf-8")) <= MAX_CHUNK_BYTES for c in chunks))
        self.assertEqual(text, "".join(chunks))


class EncodeAndAssembleTests(unittest.TestCase):
    def test_payloads_fit_a_notify_and_reassemble(self) -> None:
        text = '{"t":"snapshot","blob":"' + "é" * 20000 + '"}'
        payloads = encode_payloads(ROOM, text)
        assembler = ChunkAssembler()

        results = [assembler.feed(_parsed(p), now=0.0) for p in payloads]

        self.assertTrue(all(len(p.encode("utf-8")) < 8000 for p in payloads))
        self.assertEqual([None] * (len(payloads) - 1) + [text], results)
        self.assertEqual(0, assembler.pending_count())

    def test_oversized_message_is_refused(self) -> None:
        with self.assertRaises(MessageTooLargeError):
            encode_payloads(ROOM, "x" * (2 * 1024 * 1024 + 1))

    def test_a_message_whose_chunks_stop_arriving_expires(self) -> None:
        first, _second = encode_payloads(ROOM, "y" * 9000)
        assembler = ChunkAssembler(ttl_seconds=5.0)

        self.assertIsNone(assembler.feed(_parsed(first), now=0.0))
        self.assertEqual(1, assembler.pending_count())
        (single,) = encode_payloads(ROOM, "next")
        self.assertEqual("next", assembler.feed(_parsed(single), now=6.0))
        self.assertEqual(0, assembler.pending_count())

    def test_a_chunk_out_of_order_drops_the_message(self) -> None:
        payloads = encode_payloads(ROOM, "z" * 15000)
        assembler = ChunkAssembler()

        self.assertIsNone(assembler.feed(_parsed(payloads[0]), now=0.0))
        self.assertIsNone(assembler.feed(_parsed(payloads[2]), now=0.0))
        self.assertEqual(0, assembler.pending_count())

    def test_parse_rejects_malformed_payloads(self) -> None:
        for bad in ("", "no-separators", "room|id|x/1|c", "room|id|2/2|c", "room|id|0/0|c"):
            self.assertIsNone(parse_payload(bad), bad)

    def test_chunk_text_may_contain_the_separator(self) -> None:
        (payload,) = encode_payloads(ROOM, "a|b|c")
        self.assertEqual("a|b|c", _parsed(payload).chunk)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_wire.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.collab'`.

- [ ] **Step 3: Implement**

`backend/app/services/collab/__init__.py`:

```python
"""Canvas collaboration: presence, cursors, live edits, follow mode and voice signalling."""
```

`backend/app/services/collab/wire.py`:

```python
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
```

- [ ] **Step 4: Run it to see it pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_wire.py -q`
Expected: 8 passed.

---

### Task 2: Protocol (identity, routing, rate limit, headers)

**Files:**
- Create: `backend/app/services/collab/protocol.py`
- Test: `backend/tests/test_canvas_collab_protocol.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_canvas_collab_protocol.py`:

```python
"""What a canvas session may send and where it goes."""

import json
import unittest
import uuid

from app.services.collab.protocol import (
    ProtocolError,
    RateLimiter,
    SessionIdentity,
    parse_collab_hash_header,
    parse_collab_session_header,
    route_client_message,
)

WRITER = SessionIdentity(
    sid=str(uuid.uuid4()), user_id=str(uuid.uuid4()), name="Ana", permission="write"
)
READER = SessionIdentity(
    sid=str(uuid.uuid4()), user_id=str(uuid.uuid4()), name="Ben", permission="read"
)


class RouteClientMessageTests(unittest.TestCase):
    def test_the_server_stamp_replaces_a_forged_sender(self) -> None:
        forged = {"sid": "x", "userId": "someone-else", "name": "Mallory", "permission": "write"}

        routed = route_client_message(
            json.dumps({"t": "presence", "state": {}, "from": forged}), READER
        )

        self.assertEqual(READER.stamp(), routed.data["from"])
        self.assertEqual({}, routed.data["state"])

    def test_presence_and_cursor_skip_the_sender(self) -> None:
        for frame in ({"t": "presence", "state": {}}, {"t": "cursor", "x": 1, "y": 2}):
            routed = route_client_message(json.dumps(frame), READER)
            self.assertEqual(READER.sid, routed.skip)
            self.assertIsNone(routed.to)

    def test_ops_and_reload_come_back_to_the_sender(self) -> None:
        for frame in ({"t": "ops", "seq": 1, "ops": []}, {"t": "reload"}):
            routed = route_client_message(json.dumps(frame), WRITER)
            self.assertIsNone(routed.skip)
            self.assertIsNone(routed.to)

    def test_read_sessions_cannot_change_the_draft(self) -> None:
        target = str(uuid.uuid4())
        for frame in (
            {"t": "ops", "seq": 1, "ops": []},
            {"t": "snapshot", "to": target, "nodes": [], "edges": []},
            {"t": "reload"},
        ):
            with self.assertRaisesRegex(ProtocolError, "write access"):
                route_client_message(json.dumps(frame), READER)

    def test_targeted_messages_need_a_valid_session(self) -> None:
        for to in (None, "", "not-a-uuid"):
            with self.assertRaisesRegex(ProtocolError, "target session"):
                route_client_message(json.dumps({"t": "signal", "to": to, "data": {}}), READER)

    def test_a_targeted_message_goes_only_to_its_target(self) -> None:
        target = str(uuid.uuid4())

        routed = route_client_message(json.dumps({"t": "signal", "to": target, "data": {}}), READER)

        self.assertEqual(target, routed.to)
        self.assertIsNone(routed.skip)
        self.assertEqual(target, routed.data["to"])

    def test_unknown_and_malformed_frames_are_refused(self) -> None:
        for raw in ("not json", "[]", "{}", '{"t": 5}', '{"t": "drop_tables"}'):
            with self.assertRaises(ProtocolError):
                route_client_message(raw, WRITER)

    def test_wire_form_carries_routing_and_data(self) -> None:
        routed = route_client_message(json.dumps({"t": "cursor", "x": 1, "y": 2}), WRITER)

        wire = json.loads(routed.to_wire())

        self.assertEqual({"to", "skip", "data"}, set(wire))
        self.assertEqual("cursor", wire["data"]["t"])


class RateLimiterTests(unittest.TestCase):
    def test_burst_then_refusal_then_recovery(self) -> None:
        limiter = RateLimiter(rate=10.0, burst=3.0, tokens=3.0, updated_at=0.0)

        self.assertEqual([True, True, True, False], [limiter.allow(0.0) for _ in range(4)])
        self.assertTrue(limiter.allow(0.2))

    def test_sustained_excess_is_reported_after_three_seconds(self) -> None:
        limiter = RateLimiter(rate=1.0, burst=1.0, tokens=0.0, updated_at=0.0)

        self.assertFalse(limiter.allow(0.0))
        self.assertFalse(limiter.sustained_excess(2.9))
        self.assertTrue(limiter.sustained_excess(3.0))


class HeaderParsingTests(unittest.TestCase):
    def test_session_header(self) -> None:
        sid = str(uuid.uuid4())
        self.assertEqual(sid, parse_collab_session_header(sid))
        self.assertEqual(sid, parse_collab_session_header(sid.upper()))
        self.assertIsNone(parse_collab_session_header("nope"))
        self.assertIsNone(parse_collab_session_header(None))

    def test_hash_header(self) -> None:
        self.assertEqual("k3x9a1", parse_collab_hash_header("k3x9a1"))
        for bad in ("UPPER", "a" * 33, "", "with space", None):
            self.assertIsNone(parse_collab_hash_header(bad), bad)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_protocol.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.collab.protocol'`.

- [ ] **Step 3: Implement**

`backend/app/services/collab/protocol.py`:

```python
"""What a canvas collaboration session may send, and where each message goes.

The server never trusts identity or permission from a client: ``route_client_message``
replaces any ``from`` the client sent with the session's own stamp, and refuses the message
types that change the shared draft unless the session can write.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.workflow_access import PERMISSION_WRITE

CLIENT_TYPES = frozenset(
    {"presence", "cursor", "ops", "sync_req", "snapshot", "reload", "signal"}
)
WRITE_ONLY_TYPES = frozenset({"ops", "snapshot", "reload"})
TARGETED_TYPES = frozenset({"sync_req", "snapshot", "signal"})
# The sender receives its own copy back; for ops that copy is the acknowledgement.
ECHO_TYPES = frozenset({"ops", "reload"})

RATE_PER_SECOND = 100.0
RATE_BURST = 200.0
SUSTAINED_EXCESS_SECONDS = 3.0
MAX_ROOM_SOCKETS = 50
PERMISSION_RECHECK_SECONDS = 60.0

_HASH_PATTERN = re.compile(r"^[0-9a-z]{1,32}$")


class ProtocolError(ValueError):
    """A client message that is dropped and answered with an ``error`` frame."""


@dataclass
class SessionIdentity:
    """Who a socket belongs to. ``permission`` changes when the periodic recheck demotes it."""

    sid: str
    user_id: str
    name: str
    permission: str

    def stamp(self) -> dict[str, str]:
        """The ``from`` object the server attaches to every message this session sends."""
        return {
            "sid": self.sid,
            "userId": self.user_id,
            "name": self.name,
            "permission": self.permission,
        }


@dataclass(frozen=True)
class RoutedMessage:
    """A message ready for the bus: ``to`` limits delivery to one session, ``skip`` excludes one."""

    to: str | None
    skip: str | None
    data: dict[str, Any]

    def to_wire(self) -> str:
        """Serialize for ``CollabHub.deliver`` on every process."""
        return json.dumps(
            {"to": self.to, "skip": self.skip, "data": self.data},
            separators=(",", ":"),
            ensure_ascii=False,
        )


class ClientEnvelope(BaseModel):
    """The fields the server reads from a client frame; the rest is relayed as sent."""

    model_config = ConfigDict(extra="allow")

    t: str
    to: str | None = None


def server_message(message_type: str, **fields: Any) -> str:
    """Serialize a frame the server sends to one socket directly."""
    return json.dumps({"t": message_type, **fields}, separators=(",", ":"), ensure_ascii=False)


def _session_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def route_client_message(raw: str, identity: SessionIdentity) -> RoutedMessage:
    """Validate one client frame and decide who receives it."""
    try:
        envelope = ClientEnvelope.model_validate_json(raw)
    except ValidationError as exc:
        raise ProtocolError("malformed message") from exc
    if envelope.t not in CLIENT_TYPES:
        raise ProtocolError(f"unknown message type {envelope.t!r}")
    if envelope.t in WRITE_ONLY_TYPES and identity.permission != PERMISSION_WRITE:
        raise ProtocolError(f"{envelope.t} needs write access")
    target: str | None = None
    if envelope.t in TARGETED_TYPES:
        target = _session_id(envelope.to)
        if target is None:
            raise ProtocolError(f"{envelope.t} needs a target session")
    data = envelope.model_dump(exclude={"to"})
    data.pop("from", None)
    data["from"] = identity.stamp()
    if target is not None:
        data["to"] = target
    skip = None if envelope.t in ECHO_TYPES or target is not None else identity.sid
    return RoutedMessage(to=target, skip=skip, data=data)


@dataclass
class RateLimiter:
    """Token bucket per socket; reports when a client keeps exceeding it."""

    rate: float = RATE_PER_SECOND
    burst: float = RATE_BURST
    tokens: float = RATE_BURST
    updated_at: float = field(default_factory=time.monotonic)
    excess_since: float | None = None

    def allow(self, now: float) -> bool:
        """Take one token; False when the bucket is empty."""
        self.tokens = min(self.burst, self.tokens + (now - self.updated_at) * self.rate)
        self.updated_at = now
        if self.tokens >= 1:
            self.tokens -= 1
            self.excess_since = None
            return True
        if self.excess_since is None:
            self.excess_since = now
        return False

    def sustained_excess(self, now: float) -> bool:
        """True once the client has been over the limit for ``SUSTAINED_EXCESS_SECONDS``."""
        return self.excess_since is not None and now - self.excess_since >= SUSTAINED_EXCESS_SECONDS


def parse_collab_session_header(value: str | None) -> str | None:
    """The canvas session id from ``X-Heym-Collab-Session``, or None when absent or invalid."""
    return _session_id(value) if isinstance(value, str) else None


def parse_collab_hash_header(value: str | None) -> str | None:
    """The state hash from ``X-Heym-Collab-Hash``, or None when absent or invalid."""
    if not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value):
        return None
    return value
```

- [ ] **Step 4: Run it to see it pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_protocol.py -q`
Expected: 12 passed.

---

### Task 3: Hub (local sockets per room)

**Files:**
- Create: `backend/app/services/collab/hub.py`
- Test: `backend/tests/test_canvas_collab_hub.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_canvas_collab_hub.py`:

```python
"""The process-local registry that hands bus messages to sockets."""

import json
import unittest
from typing import Any

from app.services.collab.hub import CollabConnection, CollabHub
from app.services.collab.protocol import RoutedMessage

ROOM = "room-1"


def _drain(connection: CollabConnection) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not connection.queue.empty():
        frames.append(json.loads(connection.queue.get_nowait()))
    return frames


class HubDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = CollabHub(max_room_sockets=2)
        self.a = CollabConnection("sid-a")
        self.b = CollabConnection("sid-b")
        self.assertTrue(self.hub.add(ROOM, self.a))
        self.assertTrue(self.hub.add(ROOM, self.b))

    def test_skip_excludes_the_sender(self) -> None:
        wire = RoutedMessage(to=None, skip="sid-a", data={"t": "cursor"}).to_wire()

        self.assertEqual(1, self.hub.deliver(ROOM, wire))
        self.assertEqual([], _drain(self.a))
        self.assertEqual([{"t": "cursor"}], _drain(self.b))

    def test_to_reaches_only_the_target(self) -> None:
        wire = RoutedMessage(to="sid-b", skip=None, data={"t": "signal"}).to_wire()

        self.assertEqual(1, self.hub.deliver(ROOM, wire))
        self.assertEqual([], _drain(self.a))
        self.assertEqual([{"t": "signal"}], _drain(self.b))

    def test_other_rooms_and_malformed_wire_are_ignored(self) -> None:
        wire = RoutedMessage(to=None, skip=None, data={"t": "ops"}).to_wire()

        self.assertEqual(0, self.hub.deliver("room-2", wire))
        self.assertEqual(0, self.hub.deliver(ROOM, "not json"))
        self.assertEqual(0, self.hub.deliver(ROOM, '{"data": 3}'))
        self.assertEqual([], _drain(self.a))

    def test_a_full_room_refuses_another_socket(self) -> None:
        self.assertFalse(self.hub.add(ROOM, CollabConnection("sid-c")))
        self.assertEqual(2, self.hub.room_size(ROOM))

    def test_removing_the_last_socket_drops_the_room(self) -> None:
        self.hub.remove(ROOM, "sid-a")
        self.hub.remove(ROOM, "sid-b")

        self.assertFalse(self.hub.has_room(ROOM))

    def test_resync_reaches_every_local_socket(self) -> None:
        self.assertEqual(2, self.hub.broadcast_resync())
        self.assertEqual([{"t": "resync"}], _drain(self.a))
        self.assertEqual([{"t": "resync"}], _drain(self.b))


class ConnectionBackpressureTests(unittest.TestCase):
    def test_a_full_queue_marks_the_socket_too_slow(self) -> None:
        connection = CollabConnection("sid", queue_size=1)

        connection.enqueue("first")
        connection.enqueue("second")

        self.assertTrue(connection.overflowed)
        self.assertEqual(1, connection.queue.qsize())
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_hub.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.collab.hub'`.

- [ ] **Step 3: Implement**

`backend/app/services/collab/hub.py`:

```python
"""Process-local registry of canvas collaboration sockets, by room.

``deliver`` runs on the bus listener's callback for every message any process published to a
room this process has sockets in. It only enqueues: each socket's writer task drains its own
queue, so one slow browser never delays the others.
"""

from __future__ import annotations

import asyncio
import json

from app.services.collab.protocol import MAX_ROOM_SOCKETS, server_message

OUTBOUND_QUEUE_SIZE = 1000


class CollabConnection:
    """The outbound side of one socket."""

    def __init__(self, sid: str, queue_size: int = OUTBOUND_QUEUE_SIZE) -> None:
        self.sid = sid
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size)
        self.overflowed = False

    def enqueue(self, text: str) -> None:
        """Queue a frame; a full queue marks the socket as too slow to keep."""
        if self.overflowed:
            return
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            self.overflowed = True


class CollabHub:
    """Rooms and their sockets on this process."""

    def __init__(self, max_room_sockets: int = MAX_ROOM_SOCKETS) -> None:
        self._max_room_sockets = max_room_sockets
        self._rooms: dict[str, dict[str, CollabConnection]] = {}

    def has_room(self, room: str) -> bool:
        """True when this process has at least one socket in ``room``."""
        return room in self._rooms

    def room_size(self, room: str) -> int:
        """Sockets in ``room`` on this process."""
        return len(self._rooms.get(room, {}))

    def add(self, room: str, connection: CollabConnection) -> bool:
        """Register a socket; False when the room is full on this process."""
        if self.room_size(room) >= self._max_room_sockets:
            return False
        self._rooms.setdefault(room, {})[connection.sid] = connection
        return True

    def remove(self, room: str, sid: str) -> None:
        """Forget a socket; the room goes away with its last socket."""
        sockets = self._rooms.get(room)
        if sockets is None:
            return
        sockets.pop(sid, None)
        if not sockets:
            self._rooms.pop(room, None)

    def deliver(self, room: str, wire_text: str) -> int:
        """Enqueue a bus message for the local sockets it addresses. Returns how many."""
        sockets = self._rooms.get(room)
        if not sockets:
            return 0
        try:
            envelope = json.loads(wire_text)
        except json.JSONDecodeError:
            return 0
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict):
            return 0
        target, skip = envelope.get("to"), envelope.get("skip")
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        delivered = 0
        for sid, connection in tuple(sockets.items()):
            if target is not None and sid != target:
                continue
            if skip is not None and sid == skip:
                continue
            connection.enqueue(text)
            delivered += 1
        return delivered

    def broadcast_resync(self) -> int:
        """Tell every local socket that messages may have been missed."""
        text = server_message("resync")
        count = 0
        for sockets in tuple(self._rooms.values()):
            for connection in tuple(sockets.values()):
                connection.enqueue(text)
                count += 1
        return count


collab_hub = CollabHub()
```

- [ ] **Step 4: Run it to see it pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_hub.py -q`
Expected: 7 passed.

---

### Task 4: Bus (LISTEN + publish) and the save notification

**Files:**
- Create: `backend/app/services/collab/bus.py`
- Create: `backend/app/services/collab/saves.py`
- Test: `backend/tests/test_canvas_collab_bus.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_canvas_collab_bus.py`:

```python
"""The collab bus: publishing with chunking, listening, resync and a real-Postgres pass."""

import asyncio
import json
import unittest
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.session import libpq_dsn
from app.services.collab.bus import CollabBus, CollabPublishError
from app.services.collab.hub import CollabConnection, CollabHub
from app.services.collab.protocol import RoutedMessage
from app.services.collab.saves import queue_collab_saved
from app.services.collab.wire import CHANNEL, encode_payloads

ROOM = "5d0c7b3a-8a1f-4a43-9a7e-0e6c1d2b3f40"


class _FakeConnection:
    """Stands in for an asyncpg connection."""

    def __init__(self) -> None:
        self.listeners: dict[str, Any] = {}
        self.executed: list[tuple[Any, ...]] = []
        self.transactions = 0
        self.closed = False
        self.fail = False
        self.probe_error: Exception | None = None

    async def add_listener(self, channel: str, callback: Any) -> None:
        self.listeners[channel] = callback

    async def execute(self, sql: str, *args: Any) -> None:
        if self.fail:
            raise ConnectionError("gone")
        if sql == "SELECT 1":
            if self.probe_error is not None:
                raise self.probe_error
            return
        self.executed.append((sql, *args))

    def transaction(self) -> Any:
        connection = self

        class _Transaction:
            async def __aenter__(self) -> None:
                connection.transactions += 1

            async def __aexit__(self, *_exc: Any) -> bool:
                return False

        return _Transaction()

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


def _drain(connection: CollabConnection) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not connection.queue.empty():
        frames.append(json.loads(connection.queue.get_nowait()))
    return frames


class BusPublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_small_message_is_one_notify_without_a_transaction(self) -> None:
        connection = _FakeConnection()
        bus = CollabBus(CollabHub(), connect=AsyncMock(return_value=connection))

        await bus.publish(ROOM, RoutedMessage(to=None, skip=None, data={"t": "cursor"}))

        self.assertEqual(0, connection.transactions)
        ((sql, channel, payload),) = connection.executed
        self.assertIn("pg_notify", sql)
        self.assertEqual(CHANNEL, channel)
        self.assertTrue(payload.startswith(f"{ROOM}|"))

    async def test_a_large_message_is_chunked_inside_one_transaction(self) -> None:
        connection = _FakeConnection()
        bus = CollabBus(CollabHub(), connect=AsyncMock(return_value=connection))

        await bus.publish(
            ROOM, RoutedMessage(to=None, skip=None, data={"t": "snapshot", "blob": "x" * 20000})
        )

        self.assertEqual(1, connection.transactions)
        self.assertEqual(3, len(connection.executed))

    async def test_a_failed_publish_reconnects_next_time(self) -> None:
        broken, healthy = _FakeConnection(), _FakeConnection()
        broken.fail = True
        bus = CollabBus(CollabHub(), connect=AsyncMock(side_effect=[broken, healthy]))
        message = RoutedMessage(to=None, skip=None, data={"t": "cursor"})

        with self.assertRaises(CollabPublishError):
            await bus.publish(ROOM, message)
        await bus.publish(ROOM, message)

        self.assertTrue(broken.closed)
        self.assertEqual(1, len(healthy.executed))


class BusListenTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivers_a_reassembled_message_to_local_sockets(self) -> None:
        hub = CollabHub()
        socket = CollabConnection("sid-a")
        hub.add(ROOM, socket)
        bus = CollabBus(hub, connect=AsyncMock())
        wire = RoutedMessage(to=None, skip=None, data={"t": "snapshot", "blob": "é" * 9000})
        payloads = encode_payloads(ROOM, wire.to_wire())

        results = [bus.handle_payload(payload, now=0.0) for payload in payloads]

        self.assertEqual([0] * (len(payloads) - 1) + [1], results)
        self.assertEqual("é" * 9000, _drain(socket)[0]["blob"])

    async def test_ignores_rooms_without_local_sockets(self) -> None:
        bus = CollabBus(CollabHub(), connect=AsyncMock())
        wire = RoutedMessage(to=None, skip=None, data={"t": "cursor"}).to_wire()

        self.assertEqual(0, bus.handle_payload(encode_payloads(ROOM, wire)[0]))

    async def test_listens_and_resyncs_after_a_reconnect(self) -> None:
        first, second = _FakeConnection(), _FakeConnection()
        first.probe_error = ConnectionError("dropped")
        hub = CollabHub()
        socket = CollabConnection("sid-a")
        hub.add(ROOM, socket)
        bus = CollabBus(hub, connect=AsyncMock(side_effect=[first, second]))

        with (
            patch("app.services.collab.bus._CONNECTION_PROBE_SECONDS", 0.01),
            patch("app.services.collab.bus._RECONNECT_DELAY_SECONDS", 0.01),
        ):
            self.assertTrue(await bus.ensure_started(timeout=1.0))
            await asyncio.sleep(0.1)
        await bus.stop()

        self.assertEqual([CHANNEL], list(second.listeners))
        self.assertGreaterEqual(_drain(socket).count({"t": "resync"}), 2)


async def _postgres_reachable() -> bool:
    try:
        connection = await asyncpg.connect(libpq_dsn(), timeout=3)
    except Exception:
        return False
    await connection.close()
    return True


class RealPostgresCollabTests(unittest.IsolatedAsyncioTestCase):
    """NOTIFY through a real server; skipped when none is reachable."""

    async def asyncSetUp(self) -> None:
        if not await _postgres_reachable():
            self.skipTest("PostgreSQL is not reachable")
        self.hub = CollabHub()
        self.socket = CollabConnection("sid-a")
        self.hub.add(ROOM, self.socket)
        self.bus = CollabBus(self.hub)
        self.addAsyncCleanup(self.bus.stop)
        self.assertTrue(await self.bus.ensure_started(timeout=5.0))

    async def _next_frame(self) -> dict[str, Any]:
        while True:
            frame = json.loads(await self.socket.queue.get())
            if frame.get("t") != "resync":
                return frame

    async def test_a_chunked_message_crosses_postgres_intact(self) -> None:
        blob = "é😀" * 6000

        await self.bus.publish(
            ROOM, RoutedMessage(to=None, skip=None, data={"t": "snapshot", "blob": blob})
        )

        frame = await asyncio.wait_for(self._next_frame(), timeout=5.0)
        self.assertEqual(blob, frame["blob"])

    async def test_a_save_notifies_the_room_when_it_commits(self) -> None:
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        self.addAsyncCleanup(engine.dispose)
        session_id = str(uuid.uuid4())

        async with AsyncSession(engine) as db:
            await queue_collab_saved(
                db, uuid.UUID(ROOM), uuid.uuid4(), session=session_id, state_hash="abc123"
            )
            await db.commit()

        frame = await asyncio.wait_for(self._next_frame(), timeout=5.0)
        self.assertEqual("saved", frame["t"])
        self.assertEqual(session_id, frame["sid"])
        self.assertEqual("abc123", frame["hash"])
        self.assertRegex(frame["updatedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_bus.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.collab.bus'`.

- [ ] **Step 3: Implement the bus**

`backend/app/services/collab/bus.py`:

```python
"""One LISTEN and one publish connection per process for canvas collaboration.

Mirrors ``chat_stream_bus.py``. Every collab frame is published with ``pg_notify`` on
``heym_collab`` and comes back to every process in Postgres commit order, so every canvas sees
one order of edits. Both connections open lazily when the first collab socket in the process
needs them; an instance nobody collaborates on holds no extra connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

from app.db.session import libpq_dsn, listener_server_settings
from app.services.collab.hub import CollabHub, collab_hub
from app.services.collab.protocol import RoutedMessage
from app.services.collab.wire import CHANNEL, ChunkAssembler, encode_payloads, parse_payload

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 2.0
# asyncpg notices a dead socket only on use; probe it so a silent drop is noticed.
_CONNECTION_PROBE_SECONDS = 15.0

Connect = Callable[[], Awaitable[Any]]


class CollabPublishError(RuntimeError):
    """Publishing failed; the publish connection is reopened on the next attempt."""


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(libpq_dsn(), server_settings=listener_server_settings())


class CollabBus:
    """Publishes collab frames and hands every received one to the local hub."""

    def __init__(self, hub: CollabHub, connect: Connect = _connect) -> None:
        self._hub = hub
        self._connect = connect
        self._assembler = ChunkAssembler()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Event | None = None
        self._running = False
        self._publisher: Any = None
        self._publish_lock: asyncio.Lock | None = None

    async def ensure_started(self, timeout: float = 2.0) -> bool:
        """Start listening if this process is not yet; True once LISTEN is in place."""
        loop = asyncio.get_running_loop()
        if self._task is None or self._task.done() or self._loop is not loop:
            self._running = True
            self._loop = loop
            self._ready = asyncio.Event()
            self._publish_lock = None
            self._publisher = None
            self._task = asyncio.create_task(self._listen_loop())
        ready = self._ready
        if ready is None:
            return False
        if not ready.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(ready.wait(), timeout=timeout)
        return ready.is_set()

    async def publish(self, room: str, message: RoutedMessage) -> None:
        """Publish one frame to ``room`` on every process.

        Raises ``MessageTooLargeError`` for an oversized frame and ``CollabPublishError`` when
        Postgres could not take it.
        """
        payloads = encode_payloads(room, message.to_wire())
        async with self._lock():
            try:
                connection = await self._publisher_connection()
                if len(payloads) == 1:
                    await connection.execute("SELECT pg_notify($1, $2)", CHANNEL, payloads[0])
                    return
                async with connection.transaction():
                    for payload in payloads:
                        await connection.execute("SELECT pg_notify($1, $2)", CHANNEL, payload)
            except Exception as exc:
                await self._drop_publisher()
                raise CollabPublishError("collab publish failed") from exc

    def handle_payload(self, payload: str, now: float | None = None) -> int:
        """Route one notification to local sockets. Returns how many sockets got a frame."""
        parsed = parse_payload(payload)
        if parsed is None or not self._hub.has_room(parsed.room):
            return 0
        text = self._assembler.feed(parsed, time.monotonic() if now is None else now)
        if text is None:
            return 0
        return self._hub.deliver(parsed.room, text)

    async def stop(self) -> None:
        """Stop listening and close both connections."""
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await task
        await self._drop_publisher()
        self._ready = None
        self._loop = None
        self._publish_lock = None

    def _lock(self) -> asyncio.Lock:
        if self._publish_lock is None:
            self._publish_lock = asyncio.Lock()
        return self._publish_lock

    async def _publisher_connection(self) -> Any:
        if self._publisher is None or self._publisher.is_closed():
            self._publisher = await self._connect()
        return self._publisher

    async def _drop_publisher(self) -> None:
        publisher, self._publisher = self._publisher, None
        if publisher is not None:
            with contextlib.suppress(Exception):
                await publisher.close()

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            self.handle_payload(payload)
        except Exception:
            logger.exception("Collab notification handling failed")

    async def _listen_loop(self) -> None:
        while self._running:
            connection: Any = None
            try:
                connection = await self._connect()
                await connection.add_listener(CHANNEL, self._on_notify)
                if self._ready is not None:
                    self._ready.set()
                # Frames sent while no LISTEN was in place are gone; let every canvas catch up.
                self._hub.broadcast_resync()
                while self._running:
                    await asyncio.sleep(_CONNECTION_PROBE_SECONDS)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Collab listener disconnected (%s); retrying in %.0fs",
                    exc,
                    _RECONNECT_DELAY_SECONDS,
                )
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


collab_bus = CollabBus(collab_hub)
```

- [ ] **Step 4: Implement the save notification**

`backend/app/services/collab/saves.py`:

```python
"""Tell a workflow's canvas room that the workflow was saved.

The notification is queued on the saving request's own session, so Postgres delivers it when
that transaction commits and never for a save that rolled back. ``now()`` inside the
transaction is the instant the update wrote to ``updated_at``, so peers adopt the revision
without reading it back. It is formatted like the API's ``updated_at`` (UTC, ``Z``).
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.collab.wire import CHANNEL

_SAVED_NOTIFY = text(
    "SELECT pg_notify(:channel, :prefix || json_build_object("
    "'to', NULL, 'skip', NULL, 'data', json_build_object("
    "'t', 'saved', "
    "'updatedAt', to_char(now() AT TIME ZONE 'UTC', "
    "'YYYY-MM-DD\"T\"HH24\\:MI\\:SS.US\"Z\"'), "
    "'sid', CAST(:sid AS text), "
    "'hash', CAST(:hash AS text), "
    "'byUserId', CAST(:by AS text)"
    "))::text)"
)


async def queue_collab_saved(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    session: str | None,
    state_hash: str | None,
) -> None:
    """Queue the ``saved`` message for ``workflow_id``'s room in the current transaction.

    ``session`` and ``state_hash`` come from the editor's save headers. Both are None for a
    save made outside a canvas (MCP, Chat build, Edit History restore); peers treat that as an
    external save.
    """
    await db.execute(
        _SAVED_NOTIFY,
        {
            "channel": CHANNEL,
            "prefix": f"{workflow_id}|{uuid.uuid4().hex}|0/1|",
            "sid": session,
            "hash": state_hash,
            "by": str(actor_id),
        },
    )
```

- [ ] **Step 5: Run it to see it pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_bus.py -q`
Expected: 6 passed, plus the two real-Postgres tests passing when `docker-compose up -d postgres` is running (skipped otherwise). If the `saved` frame test fails on the `updatedAt` format, print `frame` and fix the `to_char` pattern; do not loosen the regex.

---

### Task 5: The WebSocket endpoint

**Files:**
- Modify: `backend/app/api/deps.py` (type of `resolve_token_user_id`'s first parameter)
- Create: `backend/app/api/collab.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_canvas_collab_socket.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_canvas_collab_socket.py`:

```python
"""The canvas collaboration socket: origin, auth, permission, stamping and limits."""

import json
import time
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import collab
from app.db.models import User, Workflow
from app.services.collab.hub import CollabHub
from app.services.collab.protocol import RoutedMessage

WORKFLOW_ID = uuid.uuid4()
URL = f"/api/workflows/{WORKFLOW_ID}/collab"
SAME_ORIGIN = "http://testserver"


class _InProcessBus:
    """Delivers straight to the hub, as if Postgres had echoed the notification."""

    def __init__(self, hub: CollabHub) -> None:
        self.hub = hub

    async def ensure_started(self, timeout: float = 2.0) -> bool:
        return True

    async def publish(self, room: str, message: RoutedMessage) -> None:
        self.hub.deliver(room, message.to_wire())


class _FakeSession:
    def __init__(self, users: dict[uuid.UUID, Any], workflow: Any) -> None:
        self.users = users
        self.workflow = workflow

    async def get(self, model: Any, key: Any) -> Any:
        if model is User:
            return self.users.get(key)
        if model is Workflow:
            return self.workflow if key == self.workflow.id else None
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class CollabSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = SimpleNamespace(id=uuid.uuid4(), name="Ana")
        self.viewer = SimpleNamespace(id=uuid.uuid4(), name="Ben")
        self.workflow = SimpleNamespace(id=WORKFLOW_ID, owner_id=self.owner.id)
        self.tokens = {"owner": self.owner.id, "viewer": self.viewer.id}
        self.permissions: dict[uuid.UUID, list[str | None]] = {
            self.owner.id: ["write"],
            self.viewer.id: ["read"],
        }
        users = {self.owner.id: self.owner, self.viewer.id: self.viewer}
        hub = CollabHub()
        for target in (
            patch.object(collab, "collab_hub", hub),
            patch.object(collab, "collab_bus", _InProcessBus(hub)),
            patch.object(collab, "async_session_maker", lambda: _FakeSession(users, self.workflow)),
            patch.object(collab, "resolve_token_user_id", AsyncMock(side_effect=self._resolve)),
            patch.object(collab, "get_workflow_permission", AsyncMock(side_effect=self._permission)),
        ):
            target.start()
            self.addCleanup(target.stop)
        app = FastAPI()
        app.include_router(collab.router, prefix="/api/workflows")
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    async def _resolve(self, _connection: Any, token: str) -> uuid.UUID | None:
        return self.tokens.get(token)

    async def _permission(self, _db: Any, _workflow: Any, user_id: uuid.UUID, **_kw: Any) -> Any:
        answers = self.permissions[user_id]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def _connect(self, token: str | None = "owner", origin: str = SAME_ORIGIN) -> Any:
        headers = {"origin": origin}
        if token is not None:
            headers["cookie"] = f"access_token={token}"
        return self.client.websocket_connect(URL, headers=headers)

    def _close_code(self, socket: Any) -> int:
        with self.assertRaises(WebSocketDisconnect) as caught:
            socket.receive_json()
        return caught.exception.code

    def test_a_foreign_origin_is_refused(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self._connect(origin="https://evil.example"):
                pass
        self.assertEqual(collab.CLOSE_FORBIDDEN, caught.exception.code)

    def test_no_cookie_closes_as_unauthenticated(self) -> None:
        with self._connect(token=None) as socket:
            self.assertEqual(collab.CLOSE_UNAUTHENTICATED, self._close_code(socket))

    def test_no_access_closes_as_forbidden(self) -> None:
        self.permissions[self.viewer.id] = [None]
        with self._connect(token="viewer") as socket:
            self.assertEqual(collab.CLOSE_FORBIDDEN, self._close_code(socket))

    def test_a_read_share_is_welcomed_but_cannot_send_ops(self) -> None:
        with self._connect(token="viewer") as socket:
            welcome = socket.receive_json()
            socket.send_text(json.dumps({"t": "ops", "seq": 1, "ops": []}))
            error = socket.receive_json()

        self.assertEqual("welcome", welcome["t"])
        self.assertEqual("read", welcome["permission"])
        self.assertEqual({"t": "error", "message": "ops needs write access"}, error)

    def test_the_server_stamps_the_sender(self) -> None:
        forged = {"sid": "x", "userId": "someone", "name": "Mallory", "permission": "write"}
        with self._connect(token="owner") as ana:
            ana_welcome = ana.receive_json()
            with self._connect(token="viewer") as ben:
                ben.receive_json()
                self.assertEqual("join", ana.receive_json()["t"])
                ana.send_text(json.dumps({"t": "presence", "state": {}, "from": forged}))
                frame = ben.receive_json()

        self.assertEqual("presence", frame["t"])
        self.assertEqual(ana_welcome["sid"], frame["from"]["sid"])
        self.assertEqual("Ana", frame["from"]["name"])

    def test_leaving_is_announced_to_the_room(self) -> None:
        with self._connect(token="owner") as ana:
            ana.receive_json()
            with self._connect(token="viewer") as ben:
                ben_sid = ben.receive_json()["sid"]
                ana.receive_json()
            leave = ana.receive_json()

        self.assertEqual("leave", leave["t"])
        self.assertEqual(ben_sid, leave["from"]["sid"])

    def test_revoked_access_closes_the_socket(self) -> None:
        self.permissions[self.owner.id] = ["write", None]
        with patch.object(collab, "PERMISSION_RECHECK_SECONDS", 0.05):
            with self._connect(token="owner") as socket:
                socket.receive_json()
                self.assertEqual(collab.CLOSE_FORBIDDEN, self._close_code(socket))

    def test_demotion_to_read_stops_ops(self) -> None:
        self.permissions[self.owner.id] = ["write", "read"]
        with patch.object(collab, "PERMISSION_RECHECK_SECONDS", 0.05):
            with self._connect(token="owner") as socket:
                self.assertEqual("write", socket.receive_json()["permission"])
                time.sleep(0.2)
                socket.send_text(json.dumps({"t": "ops", "seq": 1, "ops": []}))
                error = socket.receive_json()

        self.assertEqual("ops needs write access", error["message"])

    def test_an_oversized_frame_closes_the_socket(self) -> None:
        with patch.object(collab, "MAX_MESSAGE_BYTES", 64):
            with self._connect(token="owner") as socket:
                socket.receive_json()
                socket.send_text("x" * 100)
                self.assertEqual(collab.CLOSE_TOO_LARGE, self._close_code(socket))


class OriginTests(unittest.TestCase):
    def test_listed_or_same_host_origins_pass(self) -> None:
        from starlette.datastructures import Headers

        allowed = ["http://localhost:4017"]
        cases = {
            ("http://localhost:4017", "backend:10105", None): True,
            ("https://heym.example.com", "heym.example.com", None): True,
            ("https://heym.example.com", "backend:10105", "heym.example.com"): True,
            ("https://evil.example", "heym.example.com", None): False,
            (None, "heym.example.com", None): False,
        }
        for (origin, host, forwarded), expected in cases.items():
            raw = {"host": host}
            if origin:
                raw["origin"] = origin
            if forwarded:
                raw["x-forwarded-host"] = forwarded
            self.assertEqual(expected, collab.origin_allowed(Headers(raw), allowed), raw)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_socket.py -q`
Expected: FAIL with `ImportError: cannot import name 'collab' from 'app.api'`.

- [ ] **Step 3: Let `resolve_token_user_id` take a WebSocket**

In `backend/app/api/deps.py`, add the import below `from fastapi.security import ...`:

```python
from starlette.requests import HTTPConnection
```

and change the signature (the body only reads `request.headers`, which a WebSocket has too):

```python
async def resolve_token_user_id(request: HTTPConnection, token: str) -> uuid.UUID | None:
```

- [ ] **Step 4: Implement the endpoint**

`backend/app/api/collab.py`:

```python
"""Canvas collaboration socket for one workflow.

Presence, cursors, live edits, follow state and voice signalling travel through this socket.
The server stores nothing: every frame is validated, stamped with the sender's identity and
published on ``collab_bus``, which hands it back to every process in the order Postgres
committed it. Opening a canvas is not an audited action, so ``audit()`` is not called here.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket
from starlette.datastructures import Headers

from app.api.deps import resolve_token_user_id
from app.config import settings
from app.db.models import User, Workflow
from app.db.session import async_session_maker
from app.services.collab.bus import CollabPublishError, collab_bus
from app.services.collab.hub import CollabConnection, collab_hub
from app.services.collab.protocol import (
    PERMISSION_RECHECK_SECONDS,
    ProtocolError,
    RateLimiter,
    RoutedMessage,
    SessionIdentity,
    route_client_message,
    server_message,
)
from app.services.collab.wire import MAX_MESSAGE_BYTES, MessageTooLargeError
from app.services.workflow_access import get_workflow_permission

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_ROOM_FULL = 4429
CLOSE_POLICY = 1008
CLOSE_TOO_LARGE = 1009
CLOSE_TOO_SLOW = 1013


def origin_allowed(headers: Headers, allowed_origins: list[str]) -> bool:
    """True when the page opening the socket is Heym itself.

    The socket authenticates with the ``access_token`` cookie, which a browser attaches to a
    socket that any site opens. Checking ``Origin`` stops another site from opening one as the
    signed-in user.
    """
    origin = headers.get("origin")
    if not origin:
        return False
    if origin in allowed_origins:
        return True
    origin_host = urlsplit(origin).netloc.lower()
    for name in ("host", "x-forwarded-host"):
        value = headers.get(name)
        if value and value.split(",")[0].strip().lower() == origin_host:
            return True
    return False


async def _permission(workflow_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        if workflow is None:
            return None
        return await get_workflow_permission(db, workflow, user_id)


async def _identify(
    websocket: WebSocket, workflow_id: uuid.UUID
) -> tuple[SessionIdentity | None, int]:
    token = websocket.cookies.get("access_token")
    user_id = await resolve_token_user_id(websocket, token) if token else None
    if user_id is None:
        return None, CLOSE_UNAUTHENTICATED
    async with async_session_maker() as db:
        user = await db.get(User, user_id)
    if user is None:
        return None, CLOSE_UNAUTHENTICATED
    permission = await _permission(workflow_id, user_id)
    if permission is None:
        return None, CLOSE_FORBIDDEN
    identity = SessionIdentity(
        sid=str(uuid.uuid4()), user_id=str(user.id), name=user.name, permission=permission
    )
    return identity, 0


async def _publish_quietly(room: str, message: RoutedMessage) -> None:
    try:
        await collab_bus.publish(room, message)
    except (CollabPublishError, MessageTooLargeError):
        logger.warning("Collab message for room %s was not published", room)


@router.websocket("/{workflow_id}/collab")
async def workflow_collab_socket(websocket: WebSocket, workflow_id: uuid.UUID) -> None:
    """Join the canvas room of one workflow."""
    if not origin_allowed(websocket.headers, settings.cors_origins_list):
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    identity, close_code = await _identify(websocket, workflow_id)
    # Accept before refusing so the browser sees the close code and stops reconnecting.
    await websocket.accept()
    if identity is None:
        await websocket.close(code=close_code)
        return
    room = str(workflow_id)
    connection = CollabConnection(identity.sid)
    if not collab_hub.add(room, connection):
        await websocket.close(code=CLOSE_ROOM_FULL)
        return
    try:
        await collab_bus.ensure_started()
        await websocket.send_text(server_message("welcome", **identity.stamp()))
        await _publish_quietly(
            room,
            RoutedMessage(to=None, skip=identity.sid, data={"t": "join", "from": identity.stamp()}),
        )
        await _run_session(websocket, room, workflow_id, identity, connection)
    finally:
        collab_hub.remove(room, identity.sid)
        await _publish_quietly(
            room,
            RoutedMessage(to=None, skip=identity.sid, data={"t": "leave", "from": identity.stamp()}),
        )


async def _run_session(
    websocket: WebSocket,
    room: str,
    workflow_id: uuid.UUID,
    identity: SessionIdentity,
    connection: CollabConnection,
) -> None:
    tasks = [
        asyncio.create_task(_receive_loop(websocket, room, identity, connection)),
        asyncio.create_task(_send_loop(websocket, connection)),
        asyncio.create_task(_recheck_loop(websocket, workflow_id, identity)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning("Collab session %s ended with %r", identity.sid, result)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _receive_loop(
    websocket: WebSocket, room: str, identity: SessionIdentity, connection: CollabConnection
) -> None:
    limiter = RateLimiter()
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        raw = message.get("text")
        if raw is None:
            continue
        if len(raw) > MAX_MESSAGE_BYTES or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            await websocket.close(code=CLOSE_TOO_LARGE)
            return
        now = time.monotonic()
        if not limiter.allow(now):
            if limiter.sustained_excess(now):
                await websocket.close(code=CLOSE_POLICY)
                return
            continue
        try:
            await collab_bus.publish(room, route_client_message(raw, identity))
        except (ProtocolError, MessageTooLargeError) as exc:
            connection.enqueue(server_message("error", message=str(exc)))
        except CollabPublishError:
            connection.enqueue(server_message("error", message="message not delivered"))


async def _send_loop(websocket: WebSocket, connection: CollabConnection) -> None:
    while True:
        text = await connection.queue.get()
        if connection.overflowed:
            await websocket.close(code=CLOSE_TOO_SLOW)
            return
        await websocket.send_text(text)


async def _recheck_loop(
    websocket: WebSocket, workflow_id: uuid.UUID, identity: SessionIdentity
) -> None:
    while True:
        await asyncio.sleep(PERMISSION_RECHECK_SECONDS)
        try:
            permission = await _permission(workflow_id, uuid.UUID(identity.user_id))
        except Exception:
            logger.warning("Collab permission recheck failed; keeping the session", exc_info=True)
            continue
        if permission is None:
            await websocket.close(code=CLOSE_FORBIDDEN)
            return
        identity.permission = permission
```

- [ ] **Step 5: Register the router and stop the bus on shutdown**

In `backend/app/main.py`:

1. Add `collab,` to the `from app.api import (...)` list, between `codex_oauth,` and `config,`.
2. Add next to `from app.services.chat_stream_bus import chat_stream_bus`:

```python
from app.services.collab.bus import collab_bus
```

3. In the lifespan shutdown, directly after `await chat_stream_bus.stop()`:

```python
    await collab_bus.stop()
```

4. After `app.include_router(workflows.router, prefix="/api/workflows", tags=["Workflows"])`:

```python
app.include_router(collab.router, prefix="/api/workflows", tags=["Canvas Collaboration"])
```

- [ ] **Step 6: Run it to see it pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_socket.py -q`
Expected: 10 passed.

---

### Task 6: Save announcements (editor save, Chat build, revert)

**Files:**
- Modify: `backend/app/api/workflows.py` (`update_workflow`, `revert_workflow_to_version`, imports)
- Modify: `backend/app/api/chat_build.py` (two save sites)
- Test: `backend/tests/test_canvas_collab_saves.py`
- Modify test: `backend/tests/test_chat_build_session.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_canvas_collab_saves.py`:

```python
"""Saves tell the workflow's canvas room, inside the saving transaction."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from app.api.workflows import update_workflow
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate
from app.services.collab.saves import queue_collab_saved
from app.services.collab.wire import CHANNEL


def _workflow(owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Collab workflow",
        description=None,
        nodes=[],
        edges=[],
        auth_type=WorkflowAuthType.anonymous,
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode=WebhookBodyMode.generic,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
        allow_anonymous=True,
        owner_id=owner_id,
        folder_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class QueueCollabSavedTests(unittest.IsolatedAsyncioTestCase):
    async def test_queues_one_notify_on_the_saving_session(self) -> None:
        db = AsyncMock()
        workflow_id, actor_id, sid = uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())

        await queue_collab_saved(db, workflow_id, actor_id, session=sid, state_hash="abc123")

        db.execute.assert_awaited_once()
        statement, params = db.execute.await_args.args
        self.assertIn("pg_notify", str(statement))
        self.assertEqual(CHANNEL, params["channel"])
        self.assertTrue(params["prefix"].startswith(f"{workflow_id}|"))
        self.assertTrue(params["prefix"].endswith("|0/1|"))
        self.assertEqual((sid, "abc123", str(actor_id)), (params["sid"], params["hash"], params["by"]))


class UpdateWorkflowAnnouncesTests(unittest.IsolatedAsyncioTestCase):
    async def _save(self, **headers: Any) -> tuple[AsyncMock, list[str]]:
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id)
        order: list[str] = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        db.add = lambda _row: None
        db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
        queue = AsyncMock(side_effect=lambda *_a, **_k: order.append("queue"))
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows._build_workflow_response", return_value={}),
            patch("app.api.workflows.announce_workflow_saved", AsyncMock()),
            patch("app.api.workflows.queue_collab_saved", queue),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=WorkflowUpdate(nodes=[], edges=[]),
                current_user=SimpleNamespace(id=owner_id),
                db=db,
                **headers,
            )
        return queue, order

    async def test_an_editor_save_names_its_session_before_commit(self) -> None:
        sid = str(uuid.uuid4())

        queue, order = await self._save(collab_session=sid, collab_hash="k3x9")

        self.assertEqual(sid, queue.await_args.kwargs["session"])
        self.assertEqual("k3x9", queue.await_args.kwargs["state_hash"])
        self.assertEqual(["queue", "commit"], order)

    async def test_invalid_headers_count_as_an_external_save(self) -> None:
        queue, _order = await self._save(collab_session="nope", collab_hash="BAD!")

        self.assertIsNone(queue.await_args.kwargs["session"])
        self.assertIsNone(queue.await_args.kwargs["state_hash"])

    async def test_a_save_without_headers_is_external(self) -> None:
        queue, _order = await self._save()

        self.assertIsNone(queue.await_args.kwargs["session"])
```

In `backend/tests/test_chat_build_session.py`, in `ChatBuildSessionTests.setUp` add before `self.stack = ExitStack()`:

```python
        self.queue_saved = AsyncMock()
```

add this entry to the patched-names dict (next to `"announce_workflow_saved": self.announce,`):

```python
            "queue_collab_saved": self.queue_saved,
```

and add these tests to the class:

```python
    async def test_saving_an_existing_workflow_tells_its_canvas_room(self) -> None:
        self.target = Workflow(
            id=uuid.uuid4(), owner_id=self.user.id, name="Old", description="", nodes=[], edges=[]
        )
        session = self._session(target=self.target.id)

        await session.call("save_workflow", {"workflow": DSL})

        self.queue_saved.assert_awaited_once()
        self.assertEqual(self.target.id, self.queue_saved.await_args.args[1])
        self.assertIsNone(self.queue_saved.await_args.kwargs["session"])

    async def test_a_new_workflow_has_no_canvas_room_to_tell(self) -> None:
        session = self._session()

        await session.call("save_workflow", {"workflow": DSL})

        self.queue_saved.assert_not_awaited()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_saves.py tests/test_chat_build_session.py -q`
Expected: FAIL. `update_workflow() got an unexpected keyword argument 'collab_session'` and `chat_build has no attribute 'queue_collab_saved'`.

- [ ] **Step 3: Wire the editor save and revert**

In `backend/app/api/workflows.py`:

1. Add `Header` to `from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status`.
2. Add the imports (ruff will sort them):

```python
from app.services.collab.protocol import parse_collab_hash_header, parse_collab_session_header
from app.services.collab.saves import queue_collab_saved
```

3. Extend `update_workflow`'s signature after `db: AsyncSession = Depends(get_db),`:

```python
    collab_session: Annotated[str | None, Header(alias="X-Heym-Collab-Session")] = None,
    collab_hash: Annotated[str | None, Header(alias="X-Heym-Collab-Hash")] = None,
```

4. In `update_workflow`, directly before the `await db.flush()` that precedes `await db.commit()` and `await announce_workflow_saved(workflow, current_user.id, publish=publish_event)`:

```python
    # Delivered when this transaction commits; peers on the canvas adopt the new revision.
    await queue_collab_saved(
        db,
        workflow.id,
        current_user.id,
        session=parse_collab_session_header(collab_session),
        state_hash=parse_collab_hash_header(collab_hash),
    )
```

5. In `revert_workflow_to_version`, directly before its `await db.flush()`:

```python
    await queue_collab_saved(db, workflow.id, current_user.id, session=None, state_hash=None)
```

- [ ] **Step 4: Wire Chat build**

In `backend/app/api/chat_build.py`, add the import:

```python
from app.services.collab.saves import queue_collab_saved
```

At both save sites (the `save_workflow` handler and `_persist_skill`), directly before `await self.db.commit()`:

```python
        if existing is not None:
            await queue_collab_saved(
                self.db, workflow.id, self.user.id, session=None, state_hash=None
            )
```

- [ ] **Step 5: Run them to see them pass, then the neighbours**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_canvas_collab_saves.py tests/test_chat_build_session.py tests/test_workflow_update_websocket_sync.py tests/test_advisory_collaborator_error_workflow.py tests/test_advisory_collaborator_auth_downgrade.py tests/test_workflow_save_service.py -q`
Expected: all pass. Existing `db.commit.assert_awaited_once()` assertions still hold because the notify adds no commit.

- [ ] **Step 6: Lint the backend**

Run: `cd backend && uv run ruff check --fix . && uv run ruff format .`
Expected: no remaining errors.

---

### Task 7: Frontend protocol types and colors

**Files:**
- Create: `frontend/src/features/collab/types.ts`
- Create: `frontend/src/features/collab/colors.ts`
- Test: `frontend/src/features/collab/colors.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/collab/colors.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { COLLAB_COLORS, collabColor } from "@/features/collab/colors";

describe("collabColor", () => {
  it("gives a user the same palette color every time", () => {
    expect(collabColor("user-1")).toBe(collabColor("user-1"));
    expect(COLLAB_COLORS).toContain(collabColor("user-1"));
  });

  it("spreads users across the palette", () => {
    const used = new Set(Array.from({ length: 200 }, (_, index) => collabColor(`user-${index}`)));
    expect(used.size).toBeGreaterThanOrEqual(10);
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd frontend && bunx vitest run src/features/collab/colors.test.ts`
Expected: FAIL, cannot resolve `@/features/collab/colors`.

- [ ] **Step 3: Implement**

`frontend/src/features/collab/types.ts`:

```ts
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export type CollabPermission = "read" | "write";

/** Who sent a message. The server stamps it; a client cannot set it. */
export interface CollabIdentity {
  sid: string;
  userId: string;
  name: string;
  permission: CollabPermission;
}

export interface FlowViewport {
  x: number;
  y: number;
  zoom: number;
  width: number;
  height: number;
}

/** What a follower mirrors. Rendered with the follower's own data and permissions. */
export interface FollowState {
  viewport: FlowViewport | null;
  selectedNodeId: string | null;
  panelOpen: boolean;
  panelTab: string | null;
  expression: { nodeId: string; field: string } | null;
  debugOpen: boolean;
  historyOpen: boolean;
  historyExecutionId: string | null;
  runningExecutionId: string | null;
  ownerDialog: string | null;
}

export interface PresenceState {
  follow: FollowState;
  mic: boolean;
  dirty: boolean;
  joinedAt: number;
}

export type SyncOp =
  | { k: "node.put"; id: string; node: WorkflowNode }
  | { k: "node.pos"; id: string; x: number; y: number }
  | { k: "node.del"; id: string }
  | { k: "edge.put"; id: string; edge: WorkflowEdge }
  | { k: "edge.del"; id: string };

export interface SignalPayload {
  description?: RTCSessionDescriptionInit;
  candidate?: RTCIceCandidateInit;
}

export type ServerMessage =
  | ({ t: "welcome" } & CollabIdentity)
  | { t: "join"; from: CollabIdentity }
  | { t: "leave"; from: CollabIdentity }
  | { t: "presence"; from: CollabIdentity; state: PresenceState }
  | { t: "cursor"; from: CollabIdentity; x: number | null; y: number | null }
  | { t: "ops"; from: CollabIdentity; seq: number; ops: SyncOp[] }
  | { t: "sync_req"; from: CollabIdentity; to: string }
  | {
      t: "snapshot";
      from: CollabIdentity;
      to: string;
      nodes: WorkflowNode[];
      edges: WorkflowEdge[];
    }
  | { t: "reload"; from: CollabIdentity }
  | { t: "signal"; from: CollabIdentity; to: string; data: SignalPayload }
  | {
      t: "saved";
      updatedAt: string | null;
      sid: string | null;
      hash: string | null;
      byUserId: string;
    }
  | { t: "resync" }
  | { t: "error"; message: string };

export type ClientMessage =
  | { t: "presence"; state: PresenceState }
  | { t: "cursor"; x: number | null; y: number | null }
  | { t: "ops"; seq: number; ops: SyncOp[] }
  | { t: "sync_req"; to: string }
  | { t: "snapshot"; to: string; nodes: WorkflowNode[]; edges: WorkflowEdge[] }
  | { t: "reload" }
  | { t: "signal"; to: string; data: SignalPayload };
```

`frontend/src/features/collab/colors.ts`:

```ts
/** One color per person, the same on every screen: avatar ring, cursor and follow frame. */
export const COLLAB_COLORS = [
  "#F97316",
  "#22C55E",
  "#3B82F6",
  "#EC4899",
  "#A855F7",
  "#14B8A6",
  "#EAB308",
  "#EF4444",
  "#6366F1",
  "#84CC16",
  "#06B6D4",
  "#F43F5E",
] as const;

function fnv1a(value: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function collabColor(userId: string): string {
  return COLLAB_COLORS[fnv1a(userId) % COLLAB_COLORS.length];
}
```

- [ ] **Step 4: Run it to see it pass**

Run: `cd frontend && bunx vitest run src/features/collab/colors.test.ts`
Expected: 2 passed.

---

### Task 8: Live-sync core (pure logic)

**Files:**
- Create: `frontend/src/features/collab/liveSync.ts`
- Test: `frontend/src/features/collab/liveSync.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/collab/liveSync.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { SyncOp } from "@/features/collab/types";
import type { WorkflowNode } from "@/types/workflow";
import {
  PendingKeys,
  applyOps,
  buildBaseline,
  mergeSnapshot,
  nodeDataKey,
  nodePosKey,
  rebaseHistory,
  stateHash,
  takeDiff,
  type SyncBaseline,
  type SyncGraph,
} from "@/features/collab/liveSync";

function node(id: string, label: string, x = 0, y = 0): WorkflowNode {
  return { id, type: "llm", position: { x, y }, data: { label } } as WorkflowNode;
}

function clone(graph: SyncGraph): SyncGraph {
  return JSON.parse(JSON.stringify(graph)) as SyncGraph;
}

function labels(graph: SyncGraph): string[] {
  return graph.nodes.map((item) => item.data.label);
}

interface SimMessage {
  from: string;
  seq: number;
  ops: SyncOp[];
}

/** One canvas in a simulated room. The log is the single order the server gives everyone. */
class SimCanvas {
  graph: SyncGraph;
  baseline: SyncBaseline;
  pending = new PendingKeys();
  seq = 0;

  constructor(
    readonly sid: string,
    start: SyncGraph,
  ) {
    this.graph = clone(start);
    this.baseline = buildBaseline(this.graph);
  }

  edit(change: (graph: SyncGraph) => void, log: SimMessage[]): void {
    change(this.graph);
    const ops = takeDiff(this.baseline, this.graph);
    this.seq += 1;
    this.pending.mark(ops, this.seq);
    log.push({ from: this.sid, seq: this.seq, ops });
  }

  receive(message: SimMessage): void {
    if (message.from === this.sid) {
      this.pending.ack(message.ops, message.seq);
      return;
    }
    this.graph = applyOps(this.graph, message.ops, (key) => this.pending.has(key), this.baseline);
  }
}

describe("takeDiff", () => {
  it("emits a put and a position for a new node, then only a position for a move", () => {
    const baseline = buildBaseline({ nodes: [], edges: [] });
    const graph: SyncGraph = { nodes: [node("a", "A", 10, 20)], edges: [] };

    expect(takeDiff(baseline, graph).map((op) => op.k)).toEqual(["node.put", "node.pos"]);
    graph.nodes[0] = { ...graph.nodes[0], position: { x: 30, y: 20 } };
    expect(takeDiff(baseline, graph)).toEqual([{ k: "node.pos", id: "a", x: 30, y: 20 }]);
    expect(takeDiff(baseline, graph)).toEqual([]);
  });

  it("emits a put for a data change and deletes for removed nodes and edges", () => {
    const graph: SyncGraph = {
      nodes: [node("a", "A"), node("b", "B")],
      edges: [{ id: "e1", source: "a", target: "b" }],
    };
    const baseline = buildBaseline(graph);

    graph.nodes[0].data.label = "A2";
    expect(takeDiff(baseline, graph).map((op) => op.k)).toEqual(["node.put"]);
    graph.nodes = [graph.nodes[0]];
    graph.edges = [];
    expect(takeDiff(baseline, graph)).toEqual([
      { k: "node.del", id: "b" },
      { k: "edge.del", id: "e1" },
    ]);
  });

  it("ignores runtime fields such as the run status", () => {
    const graph: SyncGraph = { nodes: [node("a", "A")], edges: [] };
    const baseline = buildBaseline(graph);

    graph.nodes[0] = { ...graph.nodes[0], data: { ...graph.nodes[0].data, status: "running" } };

    expect(takeDiff(baseline, graph)).toEqual([]);
  });
});

describe("applyOps", () => {
  it("keeps this canvas's run status when a peer changes the node", () => {
    const local: SyncGraph = { nodes: [node("a", "A")], edges: [] };
    local.nodes[0].data.status = "success";

    const next = applyOps(local, [{ k: "node.put", id: "a", node: node("a", "A2") }], () => false);

    expect(next.nodes[0].data.label).toBe("A2");
    expect(next.nodes[0].data.status).toBe("success");
  });

  it("creates a node where the peer placed it", () => {
    const next = applyOps(
      { nodes: [], edges: [] },
      [{ k: "node.put", id: "n", node: node("n", "N", 40, 50) }],
      () => false,
    );

    expect(next.nodes[0].position).toEqual({ x: 40, y: 50 });
  });

  it("drops a deleted node's edges and ignores an edge whose endpoint is gone", () => {
    const local: SyncGraph = {
      nodes: [node("a", "A"), node("b", "B")],
      edges: [{ id: "e1", source: "a", target: "b" }],
    };

    const next = applyOps(
      local,
      [
        { k: "node.del", id: "b" },
        { k: "edge.put", id: "e2", edge: { id: "e2", source: "a", target: "b" } },
      ],
      () => false,
    );

    expect(next.nodes.map((item) => item.id)).toEqual(["a"]);
    expect(next.edges).toEqual([]);
  });

  it("skips keys with unacknowledged local edits", () => {
    const local: SyncGraph = { nodes: [node("a", "mine")], edges: [] };

    const next = applyOps(
      local,
      [{ k: "node.put", id: "a", node: node("a", "theirs") }],
      (key) => key === nodeDataKey("a"),
    );

    expect(labels(next)).toEqual(["mine"]);
  });
});

describe("PendingKeys", () => {
  it("stays pending until the latest op for the key comes back", () => {
    const pending = new PendingKeys();
    const op: SyncOp = { k: "node.pos", id: "a", x: 1, y: 1 };

    pending.mark([op], 1);
    pending.mark([op], 2);
    pending.ack([op], 1);
    expect(pending.has(nodePosKey("a"))).toBe(true);
    pending.ack([op], 2);
    expect(pending.has(nodePosKey("a"))).toBe(false);
  });
});

describe("a simulated room", () => {
  const start: SyncGraph = { nodes: [node("a", "A")], edges: [] };

  it("converges on the later write in server order, either way round", () => {
    for (const order of [["x", "y"], ["y", "x"]]) {
      const x = new SimCanvas("x", start);
      const y = new SimCanvas("y", start);
      const sent: Record<string, SimMessage[]> = { x: [], y: [] };
      x.edit((graph) => { graph.nodes[0].data.label = "from x"; }, sent.x);
      y.edit((graph) => { graph.nodes[0].data.label = "from y"; }, sent.y);
      const log = order.flatMap((sid) => sent[sid]);

      for (const message of log) {
        x.receive(message);
        y.receive(message);
      }

      expect(labels(x.graph)).toEqual([`from ${order[1]}`]);
      expect(labels(y.graph)).toEqual([`from ${order[1]}`]);
    }
  });

  it("never jumps back a field someone is typing in", () => {
    const x = new SimCanvas("x", start);
    const y = new SimCanvas("y", start);
    const log: SimMessage[] = [];
    x.edit((graph) => { graph.nodes[0].data.label = "a"; }, log);
    y.edit((graph) => { graph.nodes[0].data.label = "other"; }, log);
    x.edit((graph) => { graph.nodes[0].data.label = "ab"; }, log);

    for (const message of log) {
      x.receive(message);
      expect(labels(x.graph)).toEqual(["ab"]);
      y.receive(message);
    }

    expect(labels(y.graph)).toEqual(["ab"]);
  });

  it("keeps a move and a settings edit from overwriting each other", () => {
    const x = new SimCanvas("x", start);
    const y = new SimCanvas("y", start);
    const log: SimMessage[] = [];
    x.edit((graph) => { graph.nodes[0].position = { x: 90, y: 90 }; }, log);
    y.edit((graph) => { graph.nodes[0].data.label = "renamed"; }, log);

    for (const message of log) {
      x.receive(message);
      y.receive(message);
    }

    for (const canvas of [x, y]) {
      expect(canvas.graph.nodes[0].position).toEqual({ x: 90, y: 90 });
      expect(labels(canvas.graph)).toEqual(["renamed"]);
    }
  });

  it("brings a late joiner to the room's state with a snapshot and buffered ops", () => {
    const x = new SimCanvas("x", start);
    const y = new SimCanvas("y", start);
    const early: SimMessage[] = [];
    x.edit((graph) => { graph.nodes[0].data.label = "A1"; }, early);
    for (const message of early) {
      x.receive(message);
      y.receive(message);
    }
    const z = new SimCanvas("z", start);
    const buffered: SimMessage[] = [];
    y.edit((graph) => { graph.nodes.push(node("n2", "B2", 50, 50)); }, buffered);
    // x answers the sync request before y's op has reached it.
    const snapshot = clone(x.graph);
    for (const message of buffered) {
      x.receive(message);
      y.receive(message);
    }

    z.graph = mergeSnapshot(z.graph, snapshot, (key) => z.pending.has(key));
    z.baseline = buildBaseline(z.graph);
    for (const message of buffered) z.receive(message);

    expect(stateHash(z.graph)).toBe(stateHash(x.graph));
    expect(stateHash(y.graph)).toBe(stateHash(x.graph));
  });
});

describe("mergeSnapshot", () => {
  it("keeps local values for unacknowledged keys", () => {
    const local: SyncGraph = { nodes: [node("a", "mine", 5, 5), node("new", "N")], edges: [] };
    const snapshot: SyncGraph = { nodes: [node("a", "theirs", 9, 9), node("gone", "G")], edges: [] };
    const pending = new Set([nodeDataKey("a"), nodeDataKey("new"), nodeDataKey("gone")]);

    const merged = mergeSnapshot(local, snapshot, (key) => pending.has(key));

    expect(merged.nodes.map((item) => [item.id, item.data.label, item.position.x])).toEqual([
      ["a", "mine", 9],
      ["new", "N", 0],
    ]);
  });
});

describe("rebaseHistory", () => {
  it("lets undo revert only this canvas's own change", () => {
    const s0: SyncGraph = { nodes: [node("a", "A"), node("b", "B")], edges: [] };
    const s1 = clone(s0);
    s1.nodes[0].data.label = "A-mine";
    const remote: SyncOp[] = [{ k: "node.put", id: "b", node: node("b", "B-theirs") }];

    const [r0, r1] = rebaseHistory([clone(s0), s1], remote, () => false);

    expect(labels(r0)).toEqual(["A", "B-theirs"]);
    expect(labels(r1)).toEqual(["A-mine", "B-theirs"]);
  });
});

describe("stateHash", () => {
  it("ignores order and runtime fields and changes with content", () => {
    const one: SyncGraph = { nodes: [node("a", "A"), node("b", "B")], edges: [] };
    const two: SyncGraph = { nodes: [node("b", "B"), node("a", "A")], edges: [] };
    two.nodes[1].data.status = "error";

    expect(stateHash(two)).toBe(stateHash(one));
    one.nodes[0].data.label = "A2";
    expect(stateHash(one)).not.toBe(stateHash(two));
    expect(stateHash(one)).toMatch(/^[0-9a-z]{1,32}$/);
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd frontend && bunx vitest run src/features/collab/liveSync.test.ts`
Expected: FAIL, cannot resolve `@/features/collab/liveSync`.

- [ ] **Step 3: Implement**

`frontend/src/features/collab/liveSync.ts`:

```ts
import type { SyncOp } from "@/features/collab/types";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

/**
 * Pure live-editing rules (Figma's method for properties): every canvas applies ops in the
 * server's order, and ignores an op for a key it has an unacknowledged edit for until that
 * edit comes back. Node data and node position are separate keys.
 */

/** Node data a run writes while it is shown; each canvas keeps its own. */
export const RUNTIME_NODE_DATA_KEYS = [
  "status",
  "retryAttempt",
  "batchRuntimeStatus",
  "batchRuntimeRawStatus",
  "batchRuntimeRequestCounts",
  "__runbookEntrance",
] as const;

export interface SyncGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

/** The last value of each key this canvas sent or received. */
export interface SyncBaseline {
  data: Map<string, string>;
  pos: Map<string, string>;
  edges: Map<string, string>;
}

export type PendingCheck = (key: string) => boolean;

type NodeData = WorkflowNode["data"];

export function nodeDataKey(id: string): string {
  return `node:${id}:data`;
}

export function nodePosKey(id: string): string {
  return `node:${id}:pos`;
}

export function edgeKey(id: string): string {
  return `edge:${id}`;
}

export function opKey(op: SyncOp): string {
  switch (op.k) {
    case "node.pos":
      return nodePosKey(op.id);
    case "node.put":
    case "node.del":
      return nodeDataKey(op.id);
    default:
      return edgeKey(op.id);
  }
}

export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) {
    return `[${value.map((item) => (item === undefined ? "null" : stableStringify(item))).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
}

export function stripRuntimeData(data: NodeData): NodeData {
  const copy = { ...data } as unknown as Record<string, unknown>;
  for (const key of RUNTIME_NODE_DATA_KEYS) delete copy[key];
  return copy as unknown as NodeData;
}

function runtimeData(data: NodeData | undefined): Partial<NodeData> {
  if (!data) return {};
  const source = data as unknown as Record<string, unknown>;
  const runtime: Record<string, unknown> = {};
  for (const key of RUNTIME_NODE_DATA_KEYS) {
    if (source[key] !== undefined) runtime[key] = source[key];
  }
  return runtime as Partial<NodeData>;
}

export function plainEdge(edge: WorkflowEdge): WorkflowEdge {
  const plain: WorkflowEdge = { id: edge.id, source: edge.source, target: edge.target };
  if (edge.sourceHandle) plain.sourceHandle = edge.sourceHandle;
  if (edge.targetHandle) plain.targetHandle = edge.targetHandle;
  return plain;
}

/** The node as other canvases receive it: no runtime fields, plain JSON. */
export function syncedNode(node: WorkflowNode): WorkflowNode {
  return JSON.parse(
    JSON.stringify({
      id: node.id,
      type: node.type,
      position: node.position,
      data: stripRuntimeData(node.data),
    }),
  ) as WorkflowNode;
}

function dataValue(node: WorkflowNode): string {
  return stableStringify({ type: node.type, data: stripRuntimeData(node.data) });
}

function posValue(position: { x: number; y: number }): string {
  return `${position.x},${position.y}`;
}

function edgeValue(edge: WorkflowEdge): string {
  return stableStringify(plainEdge(edge));
}

export function buildBaseline(graph: SyncGraph): SyncBaseline {
  const baseline: SyncBaseline = { data: new Map(), pos: new Map(), edges: new Map() };
  for (const node of graph.nodes) {
    baseline.data.set(node.id, dataValue(node));
    baseline.pos.set(node.id, posValue(node.position));
  }
  for (const edge of graph.edges) baseline.edges.set(edge.id, edgeValue(edge));
  return baseline;
}

/** Ops that turn the baseline into `graph`. Updates the baseline to match. */
export function takeDiff(baseline: SyncBaseline, graph: SyncGraph): SyncOp[] {
  const ops: SyncOp[] = [];
  const nodeIds = new Set<string>();
  for (const node of graph.nodes) {
    nodeIds.add(node.id);
    const data = dataValue(node);
    if (baseline.data.get(node.id) !== data) {
      baseline.data.set(node.id, data);
      ops.push({ k: "node.put", id: node.id, node: syncedNode(node) });
    }
    const pos = posValue(node.position);
    if (baseline.pos.get(node.id) !== pos) {
      baseline.pos.set(node.id, pos);
      ops.push({ k: "node.pos", id: node.id, x: node.position.x, y: node.position.y });
    }
  }
  for (const id of [...baseline.data.keys()]) {
    if (nodeIds.has(id)) continue;
    baseline.data.delete(id);
    baseline.pos.delete(id);
    ops.push({ k: "node.del", id });
  }
  const edgeIds = new Set<string>();
  for (const edge of graph.edges) {
    edgeIds.add(edge.id);
    const value = edgeValue(edge);
    if (baseline.edges.get(edge.id) !== value) {
      baseline.edges.set(edge.id, value);
      ops.push({ k: "edge.put", id: edge.id, edge: plainEdge(edge) });
    }
  }
  for (const id of [...baseline.edges.keys()]) {
    if (edgeIds.has(id)) continue;
    baseline.edges.delete(id);
    ops.push({ k: "edge.del", id });
  }
  return ops;
}

/** Keys with an edit this canvas sent that has not come back from the server yet. */
export class PendingKeys {
  private readonly latest = new Map<string, number>();

  mark(ops: SyncOp[], seq: number): void {
    for (const op of ops) this.latest.set(opKey(op), seq);
  }

  ack(ops: SyncOp[], seq: number): void {
    for (const op of ops) {
      const key = opKey(op);
      const latest = this.latest.get(key);
      if (latest !== undefined && latest <= seq) this.latest.delete(key);
    }
  }

  has(key: string): boolean {
    return this.latest.has(key);
  }

  clear(): void {
    this.latest.clear();
  }
}

/** Applies remote ops, skipping pending keys. Updates `baseline` so they are not sent back. */
export function applyOps(
  graph: SyncGraph,
  ops: SyncOp[],
  isPending: PendingCheck,
  baseline?: SyncBaseline,
): SyncGraph {
  let nodes = [...graph.nodes];
  let edges = [...graph.edges];
  for (const op of ops) {
    if (isPending(opKey(op))) continue;
    switch (op.k) {
      case "node.put": {
        const index = nodes.findIndex((item) => item.id === op.id);
        const next: WorkflowNode =
          index >= 0
            ? {
                ...nodes[index],
                type: op.node.type,
                data: { ...op.node.data, ...runtimeData(nodes[index].data) },
              }
            : {
                id: op.id,
                type: op.node.type,
                position: { ...op.node.position },
                data: { ...op.node.data },
              };
        if (index >= 0) {
          nodes[index] = next;
        } else {
          nodes.push(next);
          baseline?.pos.set(op.id, posValue(next.position));
        }
        baseline?.data.set(op.id, dataValue(next));
        break;
      }
      case "node.pos": {
        const index = nodes.findIndex((item) => item.id === op.id);
        if (index < 0) break;
        nodes[index] = { ...nodes[index], position: { x: op.x, y: op.y } };
        baseline?.pos.set(op.id, posValue(nodes[index].position));
        break;
      }
      case "node.del": {
        if (!nodes.some((item) => item.id === op.id)) break;
        nodes = nodes.filter((item) => item.id !== op.id);
        baseline?.data.delete(op.id);
        baseline?.pos.delete(op.id);
        for (const edge of edges) {
          if (edge.source === op.id || edge.target === op.id) baseline?.edges.delete(edge.id);
        }
        edges = edges.filter((edge) => edge.source !== op.id && edge.target !== op.id);
        break;
      }
      case "edge.put": {
        const ids = new Set(nodes.map((item) => item.id));
        if (!ids.has(op.edge.source) || !ids.has(op.edge.target)) break;
        const edge = plainEdge(op.edge);
        const index = edges.findIndex((item) => item.id === op.id);
        if (index >= 0) edges[index] = edge;
        else edges.push(edge);
        baseline?.edges.set(op.id, edgeValue(edge));
        break;
      }
      case "edge.del": {
        if (!edges.some((item) => item.id === op.id)) break;
        edges = edges.filter((item) => item.id !== op.id);
        baseline?.edges.delete(op.id);
        break;
      }
    }
  }
  return { nodes, edges };
}

/** Applies remote ops to every undo snapshot, so undo reverts only this canvas's own edits. */
export function rebaseHistory(
  states: SyncGraph[],
  ops: SyncOp[],
  isPending: PendingCheck,
): SyncGraph[] {
  return states.map((state) => applyOps(state, ops, isPending));
}

/** A peer's snapshot, except keys this canvas has unacknowledged edits for: those stay local. */
export function mergeSnapshot(
  local: SyncGraph,
  snapshot: SyncGraph,
  isPending: PendingCheck,
): SyncGraph {
  const localNodes = new Map(local.nodes.map((item) => [item.id, item]));
  const localEdges = new Map(local.edges.map((item) => [item.id, item]));
  const nodes: WorkflowNode[] = [];
  const seenNodes = new Set<string>();
  for (const remote of snapshot.nodes) {
    seenNodes.add(remote.id);
    const mine = localNodes.get(remote.id);
    const dataPending = isPending(nodeDataKey(remote.id));
    if (dataPending && !mine) continue;
    const base: WorkflowNode =
      dataPending && mine
        ? mine
        : { ...remote, data: { ...remote.data, ...runtimeData(mine?.data) } };
    const position = isPending(nodePosKey(remote.id)) && mine ? mine.position : remote.position;
    nodes.push({ ...base, position: { ...position } });
  }
  for (const mine of local.nodes) {
    if (!seenNodes.has(mine.id) && isPending(nodeDataKey(mine.id))) nodes.push(mine);
  }
  const nodeIds = new Set(nodes.map((item) => item.id));
  const edges: WorkflowEdge[] = [];
  const seenEdges = new Set<string>();
  for (const remote of snapshot.edges) {
    seenEdges.add(remote.id);
    const pending = isPending(edgeKey(remote.id));
    const mine = localEdges.get(remote.id);
    if (pending && !mine) continue;
    edges.push(plainEdge(pending && mine ? mine : remote));
  }
  for (const mine of local.edges) {
    if (!seenEdges.has(mine.id) && isPending(edgeKey(mine.id))) edges.push(plainEdge(mine));
  }
  return {
    nodes,
    edges: edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)),
  };
}

function compareIds(a: { id: string }, b: { id: string }): number {
  if (a.id < b.id) return -1;
  if (a.id > b.id) return 1;
  return 0;
}

function cyrb53(value: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    h1 = Math.imul(h1 ^ code, 2654435761);
    h2 = Math.imul(h2 ^ code, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
  h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
  h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

/** Order-independent hash of what a save stores. Equal hashes mean the same saved graph. */
export function stateHash(graph: SyncGraph): string {
  const nodes = [...graph.nodes].sort(compareIds).map((item) =>
    stableStringify({
      id: item.id,
      type: item.type,
      position: item.position,
      data: stripRuntimeData(item.data),
    }),
  );
  const edges = [...graph.edges].sort(compareIds).map(edgeValue);
  return cyrb53(`${nodes.join("\n")}|${edges.join("\n")}`);
}
```

- [ ] **Step 4: Run it to see it pass**

Run: `cd frontend && bunx vitest run src/features/collab/liveSync.test.ts`
Expected: 15 passed. If `data: { label }` does not satisfy `NodeData` under `vue-tsc`, keep the `as WorkflowNode` cast in the test helper; do not loosen production types.

---

### Task 9: Socket client

**Files:**
- Create: `frontend/src/features/collab/collabClient.ts`

- [ ] **Step 1: Implement**

```ts
import type { ClientMessage, ServerMessage } from "@/features/collab/types";

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const MAX_QUEUED_MESSAGES = 500;
/** The server closed for a reason reconnecting cannot fix. */
const FINAL_CLOSE_CODES = new Set([4401, 4403, 4429]);

export type CollabStatus = "connecting" | "open" | "closed";

export interface CollabClientOptions {
  url: string;
  onMessage: (message: ServerMessage) => void;
  onStatus: (status: CollabStatus) => void;
}

export function collabSocketUrl(workflowId: string): string {
  const base = (import.meta.env.VITE_API_URL as string | undefined) || window.location.origin;
  return `${base.replace(/^http/, "ws")}/api/workflows/${workflowId}/collab`;
}

/** One reconnecting WebSocket to a canvas room. */
export class CollabClient {
  private socket: WebSocket | null = null;
  private queue: string[] = [];
  private retryMs = RECONNECT_MIN_MS;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(private readonly options: CollabClientOptions) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000);
    this.queue = [];
  }

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  /** Sends now, or queues while disconnected when `queueWhileClosed` is set. */
  send(message: ClientMessage, queueWhileClosed = false): void {
    const text = JSON.stringify(message);
    if (this.socket && this.isOpen) {
      this.socket.send(text);
      return;
    }
    if (queueWhileClosed && this.queue.length < MAX_QUEUED_MESSAGES) this.queue.push(text);
  }

  /** Sends what was queued while disconnected; live sync calls it once it has caught up. */
  flushQueue(): void {
    while (this.socket && this.isOpen && this.queue.length > 0) {
      const text = this.queue.shift();
      if (text !== undefined) this.socket.send(text);
    }
  }

  private connect(): void {
    this.options.onStatus("connecting");
    const socket = new WebSocket(this.options.url);
    this.socket = socket;
    socket.onopen = (): void => {
      this.retryMs = RECONNECT_MIN_MS;
      this.options.onStatus("open");
    };
    socket.onmessage = (event: MessageEvent): void => {
      if (typeof event.data !== "string") return;
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        return;
      }
      this.options.onMessage(message);
    };
    socket.onclose = (event: CloseEvent): void => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.options.onStatus("closed");
      if (this.stopped || FINAL_CLOSE_CODES.has(event.code)) return;
      this.retryTimer = setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, RECONNECT_MAX_MS);
    };
  }
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: no errors from `src/features/collab/`.

---

### Task 10: Store hooks and API headers

**Files:**
- Modify: `frontend/src/services/api.ts` (`workflowApi.update`)
- Modify: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: Let `workflowApi.update` carry headers**

In `frontend/src/services/api.ts`, change the end of `workflowApi.update` from:

```ts
  ): Promise<Workflow> => {
    const response = await api.put<Workflow>(`/workflows/${id}`, data);
    return noteWorkflowRevision(response.data);
  },
```

to (the parameter list gains `headers` after `data`):

```ts
    headers?: Record<string, string>,
  ): Promise<Workflow> => {
    const response = await api.put<Workflow>(
      `/workflows/${id}`,
      data,
      headers ? { headers } : undefined,
    );
    return noteWorkflowRevision(response.data);
  },
```

- [ ] **Step 2: Add the hook type**

In `frontend/src/stores/workflow.ts`, directly after the `interface HistoryState { ... }` block:

```ts
/** What canvas collaboration (features/collab) plugs into saving while the editor is open. */
export interface CollabStoreHooks {
  saveHeaders: (kind: "graph" | "metadata") => Record<string, string>;
  resolveConflict: (updatedAt: string | null) => Promise<boolean>;
  announceReload: () => void;
}
```

- [ ] **Step 3: Add state**

After `const workflowLoadedAt = ref<string | null>(null);`:

```ts
  let collabHooks: CollabStoreHooks | null = null;
  // Bumped by every loadWorkflow, so live sync can reset its baseline to the loaded graph.
  const graphLoadSeq = ref(0);
```

- [ ] **Step 4: Bump the load counter**

At the end of `loadWorkflow`, change:

```ts
    historyIndex.value = 0;
  }

  function knownWorkflowRevision(id: string): string | null {
```

to:

```ts
    historyIndex.value = 0;
    graphLoadSeq.value += 1;
  }

  function knownWorkflowRevision(id: string): string | null {
```

- [ ] **Step 5: Save with headers, retry once after a peer's save**

Replace `_executeSave` with:

```ts
  async function _executeSave(
    baseUpdatedAt: string | null = null,
    retriedAfterPeerSave = false,
  ): Promise<boolean> {
    const wf = currentWorkflow.value;
    if (!wf) return false;

    isSaving.value = true;
    try {
      const updated = await workflowApi.update(
        wf.id,
        {
          nodes: nodes.value,
          edges: edges.value,
          ...(baseUpdatedAt ? { base_updated_at: baseUpdatedAt } : {}),
        },
        collabHooks?.saveHeaders("graph"),
      );
      workflowLoadedAt.value = updated.updated_at;
      hasUnsavedChanges.value = false;
      return true;
    } catch (error: unknown) {
      if (!isStaleSaveConflict(error)) throw error;
      const conflictAt = conflictUpdatedAt(error);
      // A peer on the same canvas saved the shared draft a moment earlier: save on top of it.
      if (!retriedAfterPeerSave && collabHooks && (await collabHooks.resolveConflict(conflictAt))) {
        return _executeSave(conflictAt, true);
      }
      // Keep hasUnsavedChanges true: the edits are still only in this tab.
      staleSaveMode.value = "overwrite";
      staleSaveServerUpdatedAt.value = conflictAt;
      staleSaveDialogOpen.value = true;
      return false;
    } finally {
      isSaving.value = false;
    }
  }
```

- [ ] **Step 6: Announce a room-wide reload, send headers with metadata saves**

In `reloadStaleWorkflowAndRun`, directly before `await loadWorkflow(wf.id);` add:

```ts
    collabHooks?.announceReload();
```

In `updateMetadata`, change:

```ts
      const updated = await workflowApi.update(currentWorkflow.value.id, { name, description });
```

to:

```ts
      const updated = await workflowApi.update(
        currentWorkflow.value.id,
        { name, description },
        collabHooks?.saveHeaders("metadata"),
      );
```

- [ ] **Step 7: Add the collab entry points**

Directly before `async function updateMetadata(`:

```ts
  function setCollabHooks(hooks: CollabStoreHooks | null): void {
    collabHooks = hooks;
  }

  /** A peer's live edit. Not an undo step of this canvas; the undo snapshots are rebased. */
  function applyRemoteGraph(
    nextNodes: WorkflowNode[],
    nextEdges: WorkflowEdge[],
    rebase: (states: HistoryState[]) => HistoryState[],
  ): void {
    nodes.value = nextNodes;
    edges.value = nextEdges;
    history.value = rebase(history.value);
    hasUnsavedChanges.value = true;
  }

  /** A late joiner adopting the room's unsaved draft. */
  function replaceGraphFromPeer(nextNodes: WorkflowNode[], nextEdges: WorkflowEdge[]): void {
    nodes.value = nextNodes;
    edges.value = nextEdges;
    hasUnsavedChanges.value = true;
    history.value = [
      {
        nodes: JSON.parse(JSON.stringify(nextNodes)),
        edges: JSON.parse(JSON.stringify(nextEdges)),
      },
    ];
    historyIndex.value = 0;
  }

  /** A peer saved the shared draft. `matchesLocal` is null when the save carried no hash. */
  function adoptPeerSave(updatedAt: string | null, matchesLocal: boolean | null): void {
    if (updatedAt) workflowLoadedAt.value = updatedAt;
    if (matchesLocal === true) hasUnsavedChanges.value = false;
  }

  /** Re-read settings after a peer's save; nodes and edges stay live. */
  async function refreshWorkflowSettings(): Promise<void> {
    const wf = currentWorkflow.value;
    if (!wf) return;
    try {
      const fresh = await workflowApi.get(wf.id);
      if (currentWorkflow.value?.id !== fresh.id) return;
      currentWorkflow.value = { ...fresh, nodes: nodes.value, edges: edges.value };
    } catch {
      // Keep the settings shown; the next save or reload brings them in.
    }
  }

  /** Someone saved outside the canvas while this tab has unsaved edits. */
  function openExternalSaveConflict(updatedAt: string | null): void {
    staleSaveMode.value = "overwrite";
    staleSaveServerUpdatedAt.value = updatedAt;
    staleSaveDialogOpen.value = true;
  }
```

- [ ] **Step 8: Export them**

In the store's `return {`, change:

```ts
  return {
    currentWorkflow,
    nodes,
    edges,
```

to:

```ts
  return {
    currentWorkflow,
    nodes,
    edges,
    graphLoadSeq,
    currentExecutionId,
    setCollabHooks,
    applyRemoteGraph,
    replaceGraphFromPeer,
    adoptPeerSave,
    refreshWorkflowSettings,
    openExternalSaveConflict,
```

- [ ] **Step 9: Typecheck and run the existing store tests**

Run: `cd frontend && bun run typecheck && bunx vitest run src/stores`
Expected: typecheck passes; existing store specs pass.

---

### Task 11: Presence

**Files:**
- Create: `frontend/src/features/collab/usePresence.ts`

- [ ] **Step 1: Implement**

```ts
import { computed, reactive, type ComputedRef, type Ref } from "vue";

import type { CollabIdentity, CollabPermission, PresenceState } from "@/features/collab/types";
import { collabColor } from "@/features/collab/colors";

const PEER_TTL_MS = 60_000;
const CURSOR_IDLE_MS = 10_000;

export interface CollabPeer {
  identity: CollabIdentity;
  state: PresenceState | null;
  lastSeen: number;
  cursor: { x: number; y: number; at: number } | null;
}

export interface CollabUser {
  userId: string;
  name: string;
  color: string;
  permission: CollabPermission;
  sids: string[];
  isSelf: boolean;
  mic: boolean;
}

export interface RemoteCursor {
  sid: string;
  name: string;
  color: string;
  x: number;
  y: number;
}

export interface Presence {
  /** Other sessions in the room, by session id. This tab is not in it. */
  peers: Map<string, CollabPeer>;
  users: ComputedRef<CollabUser[]>;
  cursors: ComputedRef<RemoteCursor[]>;
  hasPeers: ComputedRef<boolean>;
  hasWriter: ComputedRef<boolean>;
  onJoin(identity: CollabIdentity): void;
  onPresence(identity: CollabIdentity, state: PresenceState): void;
  onCursor(identity: CollabIdentity, x: number | null, y: number | null): void;
  onLeave(sid: string): void;
  /** Drops silent peers and idle cursors; returns the dropped session ids. */
  expire(now?: number): string[];
  latestSidOf(userId: string): string | null;
  clear(): void;
}

export function createPresence(me: Ref<CollabIdentity | null>, selfMic: Ref<boolean>): Presence {
  const peers: Map<string, CollabPeer> = reactive(new Map<string, CollabPeer>());

  function touch(identity: CollabIdentity): CollabPeer {
    const existing = peers.get(identity.sid);
    if (existing) {
      existing.identity = identity;
      existing.lastSeen = Date.now();
      return existing;
    }
    peers.set(identity.sid, { identity, state: null, lastSeen: Date.now(), cursor: null });
    return peers.get(identity.sid) as CollabPeer;
  }

  function onJoin(identity: CollabIdentity): void {
    touch(identity);
  }

  function onPresence(identity: CollabIdentity, state: PresenceState): void {
    touch(identity).state = state;
  }

  function onCursor(identity: CollabIdentity, x: number | null, y: number | null): void {
    touch(identity).cursor = x === null || y === null ? null : { x, y, at: Date.now() };
  }

  function onLeave(sid: string): void {
    peers.delete(sid);
  }

  function expire(now = Date.now()): string[] {
    const removed: string[] = [];
    for (const [sid, peer] of [...peers.entries()]) {
      if (now - peer.lastSeen > PEER_TTL_MS) {
        peers.delete(sid);
        removed.push(sid);
      } else if (peer.cursor && now - peer.cursor.at > CURSOR_IDLE_MS) {
        peer.cursor = null;
      }
    }
    return removed;
  }

  function latestSidOf(userId: string): string | null {
    let latest: CollabPeer | null = null;
    for (const peer of peers.values()) {
      if (peer.identity.userId !== userId) continue;
      if (!latest || peer.lastSeen > latest.lastSeen) latest = peer;
    }
    return latest ? latest.identity.sid : null;
  }

  function clear(): void {
    peers.clear();
  }

  const users = computed<CollabUser[]>(() => {
    const byUser = new Map<string, CollabUser>();
    const self = me.value;
    if (self) {
      byUser.set(self.userId, {
        userId: self.userId,
        name: self.name,
        color: collabColor(self.userId),
        permission: self.permission,
        sids: [self.sid],
        isSelf: true,
        mic: selfMic.value,
      });
    }
    for (const peer of peers.values()) {
      const { identity } = peer;
      const known = byUser.get(identity.userId);
      if (known) {
        known.sids.push(identity.sid);
        if (identity.permission === "write") known.permission = "write";
        known.mic = known.mic || Boolean(peer.state?.mic);
        continue;
      }
      byUser.set(identity.userId, {
        userId: identity.userId,
        name: identity.name,
        color: collabColor(identity.userId),
        permission: identity.permission,
        sids: [identity.sid],
        isSelf: false,
        mic: Boolean(peer.state?.mic),
      });
    }
    return [...byUser.values()];
  });

  const cursors = computed<RemoteCursor[]>(() =>
    [...peers.values()].flatMap((peer) =>
      peer.cursor
        ? [
            {
              sid: peer.identity.sid,
              name: peer.identity.name,
              color: collabColor(peer.identity.userId),
              x: peer.cursor.x,
              y: peer.cursor.y,
            },
          ]
        : [],
    ),
  );

  const hasPeers = computed<boolean>(() => peers.size > 0);
  const hasWriter = computed<boolean>(() =>
    [...peers.values()].some((peer) => peer.identity.permission === "write"),
  );

  return {
    peers,
    users,
    cursors,
    hasPeers,
    hasWriter,
    onJoin,
    onPresence,
    onCursor,
    onLeave,
    expire,
    latestSidOf,
    clear,
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: no errors.

---

### Task 12: Live sync binding

**Files:**
- Create: `frontend/src/features/collab/useLiveSync.ts`

- [ ] **Step 1: Implement**

```ts
import { watch, type Ref } from "vue";

import type { CollabIdentity, ServerMessage, SyncOp } from "@/features/collab/types";
import type { CollabClient } from "@/features/collab/collabClient";
import type { Presence } from "@/features/collab/usePresence";
import type { useWorkflowStore } from "@/stores/workflow";
import {
  PendingKeys,
  applyOps,
  buildBaseline,
  mergeSnapshot,
  plainEdge,
  rebaseHistory,
  stateHash,
  syncedNode,
  takeDiff,
  type SyncBaseline,
  type SyncGraph,
} from "@/features/collab/liveSync";

const DIFF_INTERVAL_MS = 80;
const DRAG_INTERVAL_MS = 66;
const JOIN_SETTLE_MS = 700;
const SNAPSHOT_TIMEOUT_MS = 3000;
const PEER_SAVE_WAIT_MS = 1000;
const PEER_SAVE_POLL_MS = 100;
const REMEMBERED_PEER_SAVES = 10;

type WorkflowStore = ReturnType<typeof useWorkflowStore>;
type OpsMessage = Extract<ServerMessage, { t: "ops" }>;
type SnapshotMessage = Extract<ServerMessage, { t: "snapshot" }>;
type SavedMessage = Extract<ServerMessage, { t: "saved" }>;

export interface DragPosition {
  id: string;
  x: number;
  y: number;
}

export interface LiveSync {
  /** Catch up with the room: after (re)connecting or a server `resync`. */
  begin(): void;
  handle(message: ServerMessage): void;
  saveHeaders(kind: "graph" | "metadata"): Record<string, string>;
  resolveConflict(updatedAt: string | null): Promise<boolean>;
  announceReload(): void;
  sendDragPositions(positions: DragPosition[]): void;
  stop(): void;
}

export interface LiveSyncDeps {
  store: WorkflowStore;
  client: CollabClient;
  me: Ref<CollabIdentity | null>;
  presence: Presence;
}

/** The API formats UTC as `Z` and the 409 detail as `+00:00`; compare them as one. */
function sameRevision(a: string, b: string): boolean {
  return a.replace(/Z$/, "+00:00") === b.replace(/Z$/, "+00:00");
}

export function createLiveSync({ store, client, me, presence }: LiveSyncDeps): LiveSync {
  const pending = new PendingKeys();
  const isPending = (key: string): boolean => pending.has(key);
  const peerSaves: string[] = [];
  let baseline: SyncBaseline = buildBaseline(graph());
  let seq = 0;
  let phase: "joining" | "live" = "live";
  let buffered: OpsMessage[] = [];
  let candidates: string[] = [];
  let diffTimer: ReturnType<typeof setTimeout> | null = null;
  let joinTimer: ReturnType<typeof setTimeout> | null = null;
  let lastDragAt = 0;

  function graph(): SyncGraph {
    return { nodes: store.nodes, edges: store.edges };
  }

  function canSend(): boolean {
    return me.value?.permission === "write" && presence.hasPeers.value;
  }

  function sendOps(ops: SyncOp[]): void {
    seq += 1;
    pending.mark(ops, seq);
    client.send({ t: "ops", seq, ops }, true);
  }

  /** Sends local edits now. Alone on the canvas the baseline still advances, nothing is sent. */
  function flushLocal(): void {
    if (diffTimer) {
      clearTimeout(diffTimer);
      diffTimer = null;
    }
    const ops = takeDiff(baseline, graph());
    if (ops.length > 0 && canSend()) sendOps(ops);
  }

  function applyRemote(ops: SyncOp[]): void {
    // Unsent local keystrokes become pending first, so a remote op cannot overwrite them.
    flushLocal();
    const next = applyOps(graph(), ops, isPending, baseline);
    store.applyRemoteGraph(next.nodes, next.edges, (states) =>
      rebaseHistory(states, ops, isPending),
    );
  }

  function clearJoin(): void {
    if (joinTimer) {
      clearTimeout(joinTimer);
      joinTimer = null;
    }
  }

  function goLive(): void {
    clearJoin();
    phase = "live";
    const replay = buffered;
    buffered = [];
    for (const message of replay) applyRemote(message.ops);
    client.flushQueue();
  }

  function requestNextSnapshot(): void {
    const target = candidates.shift();
    if (!target) {
      goLive();
      return;
    }
    client.send({ t: "sync_req", to: target });
    joinTimer = setTimeout(requestNextSnapshot, SNAPSHOT_TIMEOUT_MS);
  }

  function begin(): void {
    clearJoin();
    phase = "joining";
    buffered = [];
    // Presence replies to our join tell us who holds an unsaved draft.
    joinTimer = setTimeout(() => {
      candidates = [...presence.peers.values()]
        .filter((peer) => peer.identity.permission === "write" && peer.state?.dirty)
        .sort((a, b) => (a.state?.joinedAt ?? 0) - (b.state?.joinedAt ?? 0))
        .map((peer) => peer.identity.sid);
      requestNextSnapshot();
    }, JOIN_SETTLE_MS);
  }

  function onOps(message: OpsMessage): void {
    if (message.from.sid === me.value?.sid) {
      pending.ack(message.ops, message.seq);
      return;
    }
    if (phase === "joining") {
      buffered.push(message);
      return;
    }
    applyRemote(message.ops);
  }

  function onSnapshot(message: SnapshotMessage): void {
    if (phase !== "joining" || message.from.permission !== "write") return;
    const merged = mergeSnapshot(
      graph(),
      { nodes: message.nodes, edges: message.edges },
      isPending,
    );
    store.replaceGraphFromPeer(merged.nodes, merged.edges);
    baseline = buildBaseline(merged);
    goLive();
  }

  function onSyncRequest(from: CollabIdentity): void {
    if (me.value?.permission !== "write") return;
    flushLocal();
    client.send({
      t: "snapshot",
      to: from.sid,
      nodes: store.nodes.map(syncedNode),
      edges: store.edges.map(plainEdge),
    });
  }

  async function reloadSaved(): Promise<void> {
    const id = store.currentWorkflow?.id;
    if (id) await store.loadWorkflow(id);
  }

  function onSaved(message: SavedMessage): void {
    if (message.sid && message.sid === me.value?.sid) return;
    if (message.sid && presence.peers.has(message.sid)) {
      if (message.updatedAt) {
        peerSaves.push(message.updatedAt);
        if (peerSaves.length > REMEMBERED_PEER_SAVES) peerSaves.shift();
      }
      const matches = message.hash === null ? null : message.hash === stateHash(graph());
      store.adoptPeerSave(message.updatedAt, matches);
      void store.refreshWorkflowSettings();
      return;
    }
    if (!store.hasUnsavedChanges) {
      void reloadSaved();
      return;
    }
    if (me.value?.permission === "write") store.openExternalSaveConflict(message.updatedAt);
  }

  function handle(message: ServerMessage): void {
    switch (message.t) {
      case "ops":
        onOps(message);
        return;
      case "snapshot":
        onSnapshot(message);
        return;
      case "sync_req":
        onSyncRequest(message.from);
        return;
      case "reload":
        if (message.from.sid !== me.value?.sid) void reloadSaved();
        return;
      case "saved":
        onSaved(message);
        return;
      default:
        return;
    }
  }

  async function resolveConflict(updatedAt: string | null): Promise<boolean> {
    if (!updatedAt) return false;
    const deadline = Date.now() + PEER_SAVE_WAIT_MS;
    for (;;) {
      if (peerSaves.some((seen) => sameRevision(seen, updatedAt))) return true;
      if (Date.now() >= deadline) return false;
      await new Promise((resolve) => setTimeout(resolve, PEER_SAVE_POLL_MS));
    }
  }

  function saveHeaders(kind: "graph" | "metadata"): Record<string, string> {
    const self = me.value;
    if (!self) return {};
    flushLocal();
    const headers: Record<string, string> = { "X-Heym-Collab-Session": self.sid };
    if (kind === "graph") headers["X-Heym-Collab-Hash"] = stateHash(graph());
    return headers;
  }

  /** Positions while dragging; the store only learns the position on drag stop. */
  function sendDragPositions(positions: DragPosition[]): void {
    const now = Date.now();
    if (positions.length === 0 || !canSend() || now - lastDragAt < DRAG_INTERVAL_MS) return;
    lastDragAt = now;
    sendOps(positions.map((item): SyncOp => ({ k: "node.pos", id: item.id, x: item.x, y: item.y })));
  }

  const stopGraphWatch = watch(
    () => [store.nodes, store.edges],
    () => {
      if (!diffTimer) diffTimer = setTimeout(flushLocal, DIFF_INTERVAL_MS);
    },
    { deep: true },
  );
  const stopLoadWatch = watch(
    () => store.graphLoadSeq,
    () => {
      baseline = buildBaseline(graph());
      pending.clear();
    },
  );

  function stop(): void {
    stopGraphWatch();
    stopLoadWatch();
    clearJoin();
    if (diffTimer) clearTimeout(diffTimer);
    diffTimer = null;
  }

  return {
    begin,
    handle,
    saveHeaders,
    resolveConflict,
    announceReload: (): void => client.send({ t: "reload" }),
    sendDragPositions,
    stop,
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: no errors.

---

### Task 13: Follow signals and component wiring

**Files:**
- Create: `frontend/src/features/collab/followSignals.ts`
- Create: `frontend/src/features/collab/useEditorFollowSignals.ts`
- Modify: `frontend/src/components/ui/ExpressionInput.vue`
- Modify: `frontend/src/components/Panels/DebugPanel.vue`
- Modify: `frontend/src/components/Panels/ExecutionHistoryDialog.vue`
- Modify: `frontend/src/components/Dialogs/WebPortalSettingsDialog.vue`

- [ ] **Step 1: Shared signals**

`frontend/src/features/collab/followSignals.ts`:

```ts
import { reactive, ref } from "vue";

/** Editor UI state that lives inside components rather than the workflow store. */
export interface FollowSignals {
  panelOpen: boolean;
  expression: { nodeId: string; field: string } | null;
  debugOpen: boolean;
  historyOpen: boolean;
  historyExecutionId: string | null;
  ownerDialog: string | null;
}

export function emptyFollowSignals(): FollowSignals {
  return {
    panelOpen: false,
    expression: null,
    debugOpen: false,
    historyOpen: false,
    historyExecutionId: null,
    ownerDialog: null,
  };
}

/** What this tab's components report about themselves; published to followers. */
export const localFollowSignals = reactive<FollowSignals>(emptyFollowSignals());

/** The leader's signals while this tab follows someone, null otherwise. Components mirror them. */
export const followedSignals = ref<FollowSignals | null>(null);
```

- [ ] **Step 2: EditorView's part**

`frontend/src/features/collab/useEditorFollowSignals.ts`:

```ts
import { onBeforeUnmount, watch, type Ref } from "vue";

import {
  emptyFollowSignals,
  followedSignals,
  localFollowSignals,
} from "@/features/collab/followSignals";

export interface EditorFollowRefs {
  rightPanelOpen: Ref<boolean>;
  historyOpen: Ref<boolean>;
  /** Dialogs a follower must not see into; only their name travels, as a label. */
  ownerDialogs: Record<string, Readonly<Ref<boolean>>>;
}

/** Reports EditorView's panel and dialog state to followers, and mirrors a leader's. */
export function useEditorFollowSignals(refs: EditorFollowRefs): void {
  watch(refs.rightPanelOpen, (open) => { localFollowSignals.panelOpen = open; }, { immediate: true });
  watch(refs.historyOpen, (open) => { localFollowSignals.historyOpen = open; }, { immediate: true });
  watch(
    () => Object.entries(refs.ownerDialogs).find(([, open]) => open.value)?.[0] ?? null,
    (name) => { localFollowSignals.ownerDialog = name; },
    { immediate: true },
  );
  watch(
    followedSignals,
    (signals) => {
      if (!signals) return;
      if (refs.rightPanelOpen.value !== signals.panelOpen) refs.rightPanelOpen.value = signals.panelOpen;
      if (refs.historyOpen.value !== signals.historyOpen) refs.historyOpen.value = signals.historyOpen;
    },
    { deep: true },
  );
  onBeforeUnmount(() => {
    Object.assign(localFollowSignals, emptyFollowSignals());
  });
}
```

- [ ] **Step 3: Expression dialog**

In `frontend/src/components/ui/ExpressionInput.vue`, add to the imports:

```ts
import { followedSignals, localFollowSignals } from "@/features/collab/followSignals";
```

After the `function closeExpandDialog(): void { ... }` definition, add:

```ts
// Canvas collaboration: report this dialog to followers, and open it when the followed person does.
const openedByFollow = ref(false);

watch(showExpandDialog, (isOpen): void => {
  if (!props.currentNodeId || !props.fieldKey) return;
  const reported = localFollowSignals.expression;
  if (isOpen) {
    localFollowSignals.expression = { nodeId: props.currentNodeId, field: props.fieldKey };
  } else if (reported?.nodeId === props.currentNodeId && reported.field === props.fieldKey) {
    localFollowSignals.expression = null;
  }
  if (!isOpen) openedByFollow.value = false;
});

watch(
  () => followedSignals.value?.expression ?? null,
  (target): void => {
    const mine = target !== null
      && target.nodeId === props.currentNodeId
      && target.field === props.fieldKey;
    if (mine && !showExpandDialog.value) {
      openedByFollow.value = true;
      openExpandDialog();
    } else if (!mine && openedByFollow.value && showExpandDialog.value) {
      closeExpandDialog();
    }
  },
  { immediate: true },
);
```

(`ref` and `watch` are already imported in this file; confirm with `grep -n "^import { .*watch" src/components/ui/ExpressionInput.vue`.)

- [ ] **Step 4: Debug panel**

In `frontend/src/components/Panels/DebugPanel.vue`, add the import:

```ts
import { followedSignals, localFollowSignals } from "@/features/collab/followSignals";
```

After `function toggleCollapse(): void { ... }`, add:

```ts
watch(isCollapsed, (collapsed): void => { localFollowSignals.debugOpen = !collapsed; }, { immediate: true });

watch(
  () => followedSignals.value?.debugOpen,
  (open): void => {
    if (open === undefined || open === !isCollapsed.value) return;
    panelHeight.value = open ? maxHeight : collapsedHeight;
    isCollapsed.value = !open;
    workflowStore.setDebugPanelHeight(panelHeight.value);
  },
);
```

(`watch` is imported there already; if not, add it to the `vue` import.)

- [ ] **Step 5: Execution history**

In `frontend/src/components/Panels/ExecutionHistoryDialog.vue`, add the import:

```ts
import { followedSignals, localFollowSignals } from "@/features/collab/followSignals";
```

After `async function selectEntry(entryId: string): Promise<void> { ... }`, add:

```ts
watch(selectedId, (id): void => {
  if (props.open) localFollowSignals.historyExecutionId = id;
});

watch(
  () => props.open,
  (open): void => {
    if (!open) localFollowSignals.historyExecutionId = null;
  },
);

watch(
  () => followedSignals.value?.historyExecutionId ?? null,
  (id): void => {
    if (!props.open || !id || id === selectedId.value) return;
    void selectEntry(id);
  },
  { immediate: true },
);
```

- [ ] **Step 6: Portal dialog exposes whether it is open**

In `frontend/src/components/Dialogs/WebPortalSettingsDialog.vue`, change:

```ts
defineExpose({ openDialog, closeDialog });
```

to:

```ts
defineExpose({ openDialog, closeDialog, isOpen });
```

- [ ] **Step 7: Lint and typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: no errors.

---

### Task 14: Follow, the canvas bridge and cursors

**Files:**
- Create: `frontend/src/features/collab/useFollow.ts`
- Create: `frontend/src/features/collab/CollabCanvasBridge.ts`
- Create: `frontend/src/features/collab/components/CollabCursors.vue`

- [ ] **Step 1: Follow**

`frontend/src/features/collab/useFollow.ts`:

```ts
import { computed, ref, watch, type ComputedRef, type Ref } from "vue";

import type { FlowViewport, FollowState } from "@/features/collab/types";
import type { CollabPeer, Presence } from "@/features/collab/usePresence";
import type { useWorkflowStore } from "@/stores/workflow";
import { followedSignals } from "@/features/collab/followSignals";

type WorkflowStore = ReturnType<typeof useWorkflowStore>;
const PANEL_TABS = ["properties", "config"] as const;

export interface Follow {
  followingSid: Ref<string | null>;
  leader: ComputedRef<CollabPeer | null>;
  start(sid: string): void;
  stop(): void;
}

export interface FollowDeps {
  store: WorkflowStore;
  presence: Presence;
  applyViewport: (viewport: FlowViewport) => void;
}

export function createFollow({ store, presence, applyViewport }: FollowDeps): Follow {
  const followingSid = ref<string | null>(null);
  const leader = computed<CollabPeer | null>(() =>
    followingSid.value ? presence.peers.get(followingSid.value) ?? null : null,
  );

  function stop(): void {
    followingSid.value = null;
    followedSignals.value = null;
  }

  function start(sid: string): void {
    followingSid.value = sid;
  }

  function mirror(state: FollowState): void {
    followedSignals.value = {
      panelOpen: state.panelOpen,
      expression: state.expression,
      debugOpen: state.debugOpen,
      historyOpen: state.historyOpen,
      historyExecutionId: state.historyExecutionId,
      ownerDialog: state.ownerDialog,
    };
    if (state.viewport) applyViewport(state.viewport);
    const known = state.selectedNodeId === null
      || store.nodes.some((node) => node.id === state.selectedNodeId);
    if (known && state.selectedNodeId !== store.selectedNodeId) store.selectNode(state.selectedNodeId);
    const tab = PANEL_TABS.find((candidate) => candidate === state.panelTab);
    if (tab && tab !== store.propertiesPanelTab) store.propertiesPanelTab = tab;
    if (state.runningExecutionId && state.runningExecutionId !== store.currentExecutionId) {
      void store.observeExecution(state.runningExecutionId);
    }
  }

  watch(leader, (peer) => {
    if (followingSid.value && !peer) stop();
  });
  watch(
    () => leader.value?.state?.follow ?? null,
    (state) => {
      if (state) mirror(state);
    },
    { deep: true },
  );

  return { followingSid, leader, start, stop };
}
```

- [ ] **Step 2: Canvas bridge (renderless child of VueFlow)**

`frontend/src/features/collab/CollabCanvasBridge.ts`:

```ts
import { defineComponent, onBeforeUnmount, watch } from "vue";
import { useEventListener, useThrottleFn } from "@vueuse/core";
import { useVueFlow } from "@vue-flow/core";

import type { FlowViewport } from "@/features/collab/types";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

const VIEWPORT_REPORT_MS = 100;

/**
 * Lives inside VueFlow so it reaches the right Vue Flow instance: reports this canvas's
 * viewport, pointer and drags, applies a followed viewport, and stops following on a manual
 * pan or zoom.
 */
export default defineComponent({
  name: "CollabCanvasBridge",
  setup() {
    const collab = useCollabContext();
    if (!collab) return (): null => null;
    const {
      viewport,
      dimensions,
      fitBounds,
      screenToFlowCoordinate,
      onMoveStart,
      onNodeDrag,
      vueFlowRef,
    } = useVueFlow();

    const report = useThrottleFn(
      () => {
        collab.reportViewport({
          x: viewport.value.x,
          y: viewport.value.y,
          zoom: viewport.value.zoom,
          width: dimensions.value.width,
          height: dimensions.value.height,
        });
      },
      VIEWPORT_REPORT_MS,
      true,
    );
    watch([viewport, dimensions], () => { void report(); }, { deep: true, immediate: true });

    collab.setViewportApplier((target: FlowViewport) => {
      if (!target.zoom || !target.width || !target.height) return;
      void fitBounds(
        {
          x: -target.x / target.zoom,
          y: -target.y / target.zoom,
          width: target.width / target.zoom,
          height: target.height / target.zoom,
        },
        { padding: 0, duration: 150 },
      );
    });
    onBeforeUnmount(() => collab.setViewportApplier(null));

    onMoveStart(({ event }) => {
      // Programmatic moves (fitBounds) carry a zoom event without a source event.
      const userDriven = event instanceof Event
        || Boolean((event as { sourceEvent?: unknown } | null)?.sourceEvent);
      if (userDriven) collab.stopFollowing();
    });

    onNodeDrag(({ nodes }) => {
      collab.sendDragPositions(
        nodes.map((node) => ({ id: node.id, x: node.position.x, y: node.position.y })),
      );
    });

    useEventListener(vueFlowRef, "pointermove", (event: PointerEvent) => {
      const point = screenToFlowCoordinate({ x: event.clientX, y: event.clientY });
      collab.reportCursor(point.x, point.y);
    });
    useEventListener(vueFlowRef, "pointerleave", () => collab.reportCursor(null, null));

    return (): null => null;
  },
});
```

- [ ] **Step 3: Cursors**

`frontend/src/features/collab/components/CollabCursors.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { useVueFlow } from "@vue-flow/core";

import type { RemoteCursor } from "@/features/collab/usePresence";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

// Rendered in Vue Flow's zoom pane, so positions are flow coordinates.
const collab = useCollabContext();
const { viewport } = useVueFlow();
const cursors = computed<RemoteCursor[]>(() => collab?.cursors.value ?? []);
const scale = computed<number>(() => 1 / (viewport.value.zoom || 1));
</script>

<template>
  <div class="pointer-events-none absolute left-0 top-0 z-[1000]">
    <div
      v-for="cursor in cursors"
      :key="cursor.sid"
      class="absolute left-0 top-0 flex items-start transition-transform duration-100 ease-linear"
      :style="{
        transform: `translate(${cursor.x}px, ${cursor.y}px) scale(${scale})`,
        transformOrigin: '0 0',
      }"
    >
      <svg
        width="16"
        height="18"
        viewBox="0 0 16 18"
        aria-hidden="true"
      >
        <path
          d="M1 1 L15 7.5 L8.5 9.5 L6 16.5 Z"
          :fill="cursor.color"
          stroke="white"
          stroke-width="1.25"
          stroke-linejoin="round"
        />
      </svg>
      <span
        class="ml-0.5 mt-3 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium leading-none text-white shadow"
        :style="{ backgroundColor: cursor.color }"
      >{{ cursor.name }}</span>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Typecheck** (it fails until Task 16 adds `useCanvasCollab`; run it after Task 16).

---

### Task 15: Voice

**Files:**
- Create: `frontend/src/features/collab/useVoice.ts`

- [ ] **Step 1: Implement**

```ts
import { reactive, ref, type Ref } from "vue";

import type { CollabIdentity, SignalPayload } from "@/features/collab/types";

// Public STUN only: browsers learn their public address and then talk directly. No TURN relay,
// nothing for the operator to run. Offline, peers on one LAN or VPN still connect locally.
const ICE_SERVERS: RTCIceServer[] = [
  { urls: "stun:stun.cloudflare.com:3478" },
  { urls: "stun:stun.l.google.com:19302" },
];
const CONNECT_TIMEOUT_MS = 10_000;
const SPEAKING_THRESHOLD = 0.04;
const SPEAKING_POLL_MS = 150;

interface PeerLink {
  pc: RTCPeerConnection;
  polite: boolean;
  makingOffer: boolean;
  ignoreOffer: boolean;
  audio: HTMLAudioElement;
  analyser: AnalyserNode | null;
  timeout: ReturnType<typeof setTimeout> | null;
}

export interface VoiceDeps {
  me: Ref<CollabIdentity | null>;
  micOn: Ref<boolean>;
  sendSignal: (to: string, data: SignalPayload) => void;
  peerSids: () => string[];
}

export interface Voice {
  micError: Ref<string | null>;
  autoplayBlocked: Ref<boolean>;
  /** Session ids currently speaking, this tab's included. */
  speaking: Set<string>;
  /** Session ids whose audio connection failed. */
  failed: Set<string>;
  toggleMic(): Promise<void>;
  reconcile(): void;
  handleSignal(fromSid: string, data: SignalPayload): Promise<void>;
  closePeer(sid: string): void;
  closeAll(): void;
  resumeAudio(): void;
  reset(): void;
}

export function createVoice({ me, micOn, sendSignal, peerSids }: VoiceDeps): Voice {
  const micError = ref<string | null>(null);
  const autoplayBlocked = ref(false);
  const speaking: Set<string> = reactive(new Set<string>());
  const failed: Set<string> = reactive(new Set<string>());
  const links = new Map<string, PeerLink>();
  let localStream: MediaStream | null = null;
  let localAnalyser: AnalyserNode | null = null;
  let audioContext: AudioContext | null = null;
  let speakingTimer: ReturnType<typeof setInterval> | null = null;

  function context(): AudioContext {
    if (!audioContext) audioContext = new AudioContext();
    return audioContext;
  }

  function level(analyser: AnalyserNode): number {
    const samples = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const sample of samples) sum += sample * sample;
    return Math.sqrt(sum / samples.length);
  }

  function mark(target: Set<string>, sid: string, on: boolean): void {
    if (on) target.add(sid);
    else target.delete(sid);
  }

  function updateSpeaking(): void {
    const mine = me.value?.sid;
    if (mine) {
      mark(speaking, mine, micOn.value && localAnalyser !== null && level(localAnalyser) > SPEAKING_THRESHOLD);
    }
    for (const [sid, link] of links) {
      mark(speaking, sid, link.analyser !== null && level(link.analyser) > SPEAKING_THRESHOLD);
    }
  }

  function analyse(stream: MediaStream): AnalyserNode {
    const analyser = context().createAnalyser();
    analyser.fftSize = 512;
    context().createMediaStreamSource(stream).connect(analyser);
    if (!speakingTimer) speakingTimer = setInterval(updateSpeaking, SPEAKING_POLL_MS);
    return analyser;
  }

  function clearLinkTimer(link: PeerLink): void {
    if (link.timeout) clearTimeout(link.timeout);
    link.timeout = null;
  }

  function attachLocalTracks(link: PeerLink): void {
    if (!localStream) return;
    const sending = new Set(link.pc.getSenders().map((sender) => sender.track));
    for (const track of localStream.getTracks()) {
      if (!sending.has(track)) link.pc.addTrack(track, localStream);
    }
  }

  function openLink(sid: string): PeerLink {
    const existing = links.get(sid);
    if (existing) return existing;
    const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    const audio = new Audio();
    audio.autoplay = true;
    const link: PeerLink = {
      pc,
      polite: (me.value?.sid ?? "") < sid,
      makingOffer: false,
      ignoreOffer: false,
      audio,
      analyser: null,
      timeout: null,
    };
    links.set(sid, link);
    pc.onnegotiationneeded = async (): Promise<void> => {
      try {
        link.makingOffer = true;
        await pc.setLocalDescription();
        if (pc.localDescription) sendSignal(sid, { description: pc.localDescription.toJSON() });
      } catch {
        failed.add(sid);
      } finally {
        link.makingOffer = false;
      }
    };
    pc.onicecandidate = ({ candidate }): void => {
      if (candidate) sendSignal(sid, { candidate: candidate.toJSON() });
    };
    pc.ontrack = ({ streams }): void => {
      const [stream] = streams;
      if (!stream) return;
      audio.srcObject = stream;
      audio.play().catch(() => {
        autoplayBlocked.value = true;
      });
      link.analyser = analyse(stream);
    };
    pc.onconnectionstatechange = (): void => {
      if (pc.connectionState === "connected") {
        failed.delete(sid);
        clearLinkTimer(link);
      } else if (pc.connectionState === "failed") {
        failed.add(sid);
      }
    };
    link.timeout = setTimeout(() => {
      if (pc.connectionState !== "connected") failed.add(sid);
    }, CONNECT_TIMEOUT_MS);
    attachLocalTracks(link);
    return link;
  }

  /** Perfect negotiation: the impolite side ignores a colliding offer, the polite side yields. */
  async function handleSignal(fromSid: string, data: SignalPayload): Promise<void> {
    const isOffer = data.description?.type === "offer";
    const link = isOffer ? openLink(fromSid) : links.get(fromSid);
    if (!link) return;
    const { pc } = link;
    try {
      if (data.description) {
        const collision = isOffer && (link.makingOffer || pc.signalingState !== "stable");
        link.ignoreOffer = !link.polite && collision;
        if (link.ignoreOffer) return;
        await pc.setRemoteDescription(data.description);
        if (isOffer) {
          await pc.setLocalDescription();
          if (pc.localDescription) sendSignal(fromSid, { description: pc.localDescription.toJSON() });
        }
      } else if (data.candidate) {
        try {
          await pc.addIceCandidate(data.candidate);
        } catch (error) {
          if (!link.ignoreOffer) throw error;
        }
      }
    } catch {
      failed.add(fromSid);
    }
  }

  function stopMic(): void {
    for (const link of links.values()) {
      for (const sender of link.pc.getSenders()) {
        if (sender.track) link.pc.removeTrack(sender);
      }
    }
    localStream?.getTracks().forEach((track) => track.stop());
    localStream = null;
    localAnalyser = null;
    micOn.value = false;
    const mine = me.value?.sid;
    if (mine) speaking.delete(mine);
  }

  async function toggleMic(): Promise<void> {
    if (micOn.value) {
      stopMic();
      return;
    }
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      micError.value = "Microphone access was blocked";
      return;
    }
    micError.value = null;
    micOn.value = true;
    localAnalyser = analyse(localStream);
    reconcile();
  }

  function closePeer(sid: string): void {
    const link = links.get(sid);
    if (!link) return;
    clearLinkTimer(link);
    link.pc.close();
    link.audio.srcObject = null;
    links.delete(sid);
    speaking.delete(sid);
    failed.delete(sid);
  }

  function closeAll(): void {
    for (const sid of [...links.keys()]) closePeer(sid);
  }

  /** Links stay open until the peer leaves; with the mic on, every peer gets this track. */
  function reconcile(): void {
    const present = new Set(peerSids());
    for (const sid of [...links.keys()]) {
      if (!present.has(sid)) closePeer(sid);
    }
    if (!micOn.value) return;
    for (const sid of present) attachLocalTracks(openLink(sid));
  }

  function resumeAudio(): void {
    autoplayBlocked.value = false;
    void context().resume();
    for (const link of links.values()) {
      link.audio.play().catch(() => {
        autoplayBlocked.value = true;
      });
    }
  }

  function reset(): void {
    stopMic();
    closeAll();
    if (speakingTimer) clearInterval(speakingTimer);
    speakingTimer = null;
    void audioContext?.close();
    audioContext = null;
    micError.value = null;
    autoplayBlocked.value = false;
    speaking.clear();
    failed.clear();
  }

  return {
    micError,
    autoplayBlocked,
    speaking,
    failed,
    toggleMic,
    reconcile,
    handleSignal,
    closePeer,
    closeAll,
    resumeAudio,
    reset,
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: no errors in `useVoice.ts`.

---

### Task 16: Orchestrator, overlay, follow frame and mounting

**Files:**
- Create: `frontend/src/features/collab/useCanvasCollab.ts`
- Create: `frontend/src/features/collab/components/CollabOverlay.vue`
- Create: `frontend/src/features/collab/components/FollowFrame.vue`
- Modify: `frontend/src/views/EditorView.vue`
- Modify: `frontend/src/components/Canvas/WorkflowCanvas.vue`

- [ ] **Step 1: Orchestrator**

`frontend/src/features/collab/useCanvasCollab.ts`:

```ts
import {
  computed,
  inject,
  onBeforeUnmount,
  provide,
  ref,
  watch,
  type ComputedRef,
  type InjectionKey,
  type Ref,
} from "vue";
import { useEventListener, useThrottleFn } from "@vueuse/core";

import type { CollabIdentity, FlowViewport, FollowState, ServerMessage } from "@/features/collab/types";
import type { CollabUser, RemoteCursor } from "@/features/collab/usePresence";
import type { DragPosition, LiveSync } from "@/features/collab/useLiveSync";
import { CollabClient, collabSocketUrl, type CollabStatus } from "@/features/collab/collabClient";
import { localFollowSignals } from "@/features/collab/followSignals";
import { createFollow } from "@/features/collab/useFollow";
import { createLiveSync } from "@/features/collab/useLiveSync";
import { createPresence } from "@/features/collab/usePresence";
import { createVoice } from "@/features/collab/useVoice";
import { useWorkflowStore } from "@/stores/workflow";

const HEARTBEAT_MS = 20_000;
const EXPIRY_CHECK_MS = 5_000;
const PRESENCE_THROTTLE_MS = 100;
const CURSOR_THROTTLE_MS = 66;

export interface CollabUserView extends CollabUser {
  speaking: boolean;
  audioFailed: boolean;
  following: boolean;
}

export interface CollabContext {
  me: Ref<CollabIdentity | null>;
  status: Ref<CollabStatus>;
  users: ComputedRef<CollabUserView[]>;
  cursors: ComputedRef<RemoteCursor[]>;
  followedUser: ComputedRef<CollabUserView | null>;
  followedOwnerDialog: ComputedRef<string | null>;
  toggleFollow(userId: string): void;
  stopFollowing(): void;
  micOn: Ref<boolean>;
  micError: Ref<string | null>;
  autoplayBlocked: Ref<boolean>;
  toggleMic(): Promise<void>;
  resumeAudio(): void;
  reportViewport(viewport: FlowViewport): void;
  reportCursor(x: number | null, y: number | null): void;
  setViewportApplier(apply: ((viewport: FlowViewport) => void) | null): void;
  sendDragPositions(positions: DragPosition[]): void;
}

export const COLLAB_CONTEXT: InjectionKey<CollabContext> = Symbol("canvas-collab");

export function useCollabContext(): CollabContext | null {
  return inject(COLLAB_CONTEXT, null);
}

/** Joins the canvas room of `workflowId` while it is set and provides the context below. */
export function useCanvasCollab(workflowId: Ref<string | null>): CollabContext {
  const store = useWorkflowStore();
  const me = ref<CollabIdentity | null>(null);
  const status = ref<CollabStatus>("closed");
  const micOn = ref(false);
  const localViewport = ref<FlowViewport | null>(null);
  const presence = createPresence(me, micOn);
  let client: CollabClient | null = null;
  let liveSync: LiveSync | null = null;
  let joinedAt = 0;
  let viewportApplier: ((viewport: FlowViewport) => void) | null = null;
  let timers: Array<ReturnType<typeof setInterval>> = [];

  const voice = createVoice({
    me,
    micOn,
    sendSignal: (to, data) => client?.send({ t: "signal", to, data }),
    peerSids: () => [...presence.peers.keys()],
  });
  const follow = createFollow({
    store,
    presence,
    applyViewport: (viewport) => viewportApplier?.(viewport),
  });

  function followState(): FollowState {
    return {
      viewport: localViewport.value,
      selectedNodeId: store.selectedNodeId,
      panelOpen: localFollowSignals.panelOpen,
      panelTab: store.propertiesPanelTab,
      expression: localFollowSignals.expression,
      debugOpen: localFollowSignals.debugOpen,
      historyOpen: localFollowSignals.historyOpen,
      historyExecutionId: localFollowSignals.historyExecutionId,
      runningExecutionId: store.isExecuting ? store.currentExecutionId : null,
      ownerDialog: localFollowSignals.ownerDialog,
    };
  }

  function sendPresence(): void {
    if (!client || !me.value) return;
    client.send({
      t: "presence",
      state: { follow: followState(), mic: micOn.value, dirty: store.hasUnsavedChanges, joinedAt },
    });
  }

  const sendPresenceSoon = useThrottleFn(
    () => {
      if (presence.hasPeers.value) sendPresence();
    },
    PRESENCE_THROTTLE_MS,
    true,
  );
  watch(
    () => [followState(), micOn.value, store.hasUnsavedChanges],
    () => { void sendPresenceSoon(); },
    { deep: true },
  );

  const sendCursor = useThrottleFn(
    (x: number | null, y: number | null) => client?.send({ t: "cursor", x, y }),
    CURSOR_THROTTLE_MS,
    true,
  );

  /** Unsaved changes belong to people who can save them. */
  function dropWriterlessDraft(): void {
    if (me.value?.permission !== "read" || !store.hasUnsavedChanges || presence.hasWriter.value) return;
    const id = store.currentWorkflow?.id;
    if (id) void store.loadWorkflow(id);
  }

  function onMessage(message: ServerMessage): void {
    if (message.t === "welcome") {
      me.value = {
        sid: message.sid,
        userId: message.userId,
        name: message.name,
        permission: message.permission,
      };
      if (!joinedAt) joinedAt = Date.now();
      presence.clear();
      voice.closeAll();
      sendPresence();
      liveSync?.begin();
      return;
    }
    if (!me.value) return;
    switch (message.t) {
      case "join":
        presence.onJoin(message.from);
        sendPresence();
        return;
      case "leave":
        presence.onLeave(message.from.sid);
        voice.closePeer(message.from.sid);
        dropWriterlessDraft();
        return;
      case "presence":
        presence.onPresence(message.from, message.state);
        voice.reconcile();
        return;
      case "cursor":
        presence.onCursor(message.from, message.x, message.y);
        return;
      case "signal":
        void voice.handleSignal(message.from.sid, message.data);
        return;
      case "resync":
        liveSync?.begin();
        return;
      case "error":
        return;
      default:
        liveSync?.handle(message);
    }
  }

  function start(id: string): void {
    const session = new CollabClient({
      url: collabSocketUrl(id),
      onMessage,
      onStatus: (next) => { status.value = next; },
    });
    const sync = createLiveSync({ store, client: session, me, presence });
    client = session;
    liveSync = sync;
    store.setCollabHooks({
      saveHeaders: (kind) => sync.saveHeaders(kind),
      resolveConflict: (updatedAt) => sync.resolveConflict(updatedAt),
      announceReload: () => sync.announceReload(),
    });
    session.start();
    timers = [
      setInterval(sendPresence, HEARTBEAT_MS),
      setInterval(() => {
        const removed = presence.expire();
        for (const sid of removed) voice.closePeer(sid);
        if (removed.length > 0) dropWriterlessDraft();
      }, EXPIRY_CHECK_MS),
    ];
  }

  function stop(): void {
    timers.forEach(clearInterval);
    timers = [];
    follow.stop();
    voice.reset();
    liveSync?.stop();
    liveSync = null;
    client?.stop();
    client = null;
    store.setCollabHooks(null);
    presence.clear();
    me.value = null;
    joinedAt = 0;
    status.value = "closed";
  }

  watch(
    workflowId,
    (id) => {
      stop();
      if (id) start(id);
    },
    { immediate: true },
  );
  onBeforeUnmount(stop);
  useEventListener(window, "keydown", (event: KeyboardEvent) => {
    if (event.key === "Escape" && follow.followingSid.value) follow.stop();
  });

  const users = computed<CollabUserView[]>(() =>
    presence.users.value.map((user) => ({
      ...user,
      speaking: user.sids.some((sid) => voice.speaking.has(sid)),
      audioFailed: !user.isSelf && user.sids.some((sid) => voice.failed.has(sid)),
      following: follow.followingSid.value !== null && user.sids.includes(follow.followingSid.value),
    })),
  );
  const followedUser = computed<CollabUserView | null>(
    () => users.value.find((user) => user.following) ?? null,
  );
  const followedOwnerDialog = computed<string | null>(
    () => follow.leader.value?.state?.follow.ownerDialog ?? null,
  );

  const context: CollabContext = {
    me,
    status,
    users,
    cursors: presence.cursors,
    followedUser,
    followedOwnerDialog,
    toggleFollow(userId: string): void {
      const user = users.value.find((candidate) => candidate.userId === userId);
      if (!user || user.isSelf) return;
      if (user.following) {
        follow.stop();
        return;
      }
      const sid = presence.latestSidOf(userId);
      if (sid) follow.start(sid);
    },
    stopFollowing: (): void => follow.stop(),
    micOn,
    micError: voice.micError,
    autoplayBlocked: voice.autoplayBlocked,
    toggleMic: (): Promise<void> => voice.toggleMic(),
    resumeAudio: (): void => voice.resumeAudio(),
    reportViewport(viewport: FlowViewport): void {
      localViewport.value = viewport;
    },
    reportCursor(x: number | null, y: number | null): void {
      if (presence.hasPeers.value) void sendCursor(x, y);
    },
    setViewportApplier(apply: ((viewport: FlowViewport) => void) | null): void {
      viewportApplier = apply;
    },
    sendDragPositions(positions: DragPosition[]): void {
      liveSync?.sendDragPositions(positions);
    },
  };
  provide(COLLAB_CONTEXT, context);
  return context;
}
```

- [ ] **Step 2: Overlay**

`frontend/src/features/collab/components/CollabOverlay.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { Mic, MicOff, Volume2 } from "lucide-vue-next";

import type { CollabUserView } from "@/features/collab/useCanvasCollab";
import UserAvatar from "@/components/ui/UserAvatar.vue";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

const MAX_VISIBLE = 5;

const collab = useCollabContext();
const users = computed<CollabUserView[]>(() => collab?.users.value ?? []);
const visible = computed<CollabUserView[]>(() => users.value.slice(0, MAX_VISIBLE));
const hiddenCount = computed<number>(() => Math.max(0, users.value.length - MAX_VISIBLE));
const micLabel = computed<string>(() => {
  if (collab?.micError.value) return collab.micError.value;
  return collab?.micOn.value ? "Turn microphone off" : "Turn microphone on";
});

function avatarLabel(user: CollabUserView): string {
  const role = user.permission === "write" ? "can edit" : "can view";
  if (user.isSelf) return `${user.name} (you) · ${role}`;
  const action = user.following ? "click to stop following" : "click to follow";
  return `${user.name} · ${role} · ${action}`;
}

function ringStyle(user: CollabUserView): Record<string, string> {
  const width = user.following ? 5 : 4;
  return { boxShadow: `0 0 0 2px hsl(var(--background)), 0 0 0 ${width}px ${user.color}` };
}
</script>

<template>
  <div
    v-if="collab && collab.me.value"
    class="absolute left-3 top-3 z-20 hidden items-center gap-2 md:flex"
    data-testid="collab-overlay"
  >
    <div class="flex items-center -space-x-1">
      <button
        v-for="user in visible"
        :key="user.userId"
        type="button"
        class="relative rounded-full"
        :class="user.isSelf ? 'cursor-default' : 'cursor-pointer'"
        :style="ringStyle(user)"
        :title="avatarLabel(user)"
        :aria-label="avatarLabel(user)"
        @click="collab.toggleFollow(user.userId)"
      >
        <UserAvatar
          :user-id="user.userId"
          :name="user.name"
          class="h-7 w-7 bg-muted text-xs font-semibold text-foreground"
          :class="user.speaking ? 'animate-pulse' : ''"
        />
        <span
          v-if="user.mic"
          class="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-background"
        >
          <Mic
            class="h-2.5 w-2.5"
            :style="{ color: user.color }"
          />
        </span>
        <span
          v-if="user.audioFailed"
          class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-destructive"
          title="No audio connection"
        />
      </button>
      <span
        v-if="hiddenCount > 0"
        class="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-[11px] font-medium text-muted-foreground ring-2 ring-background"
      >+{{ hiddenCount }}</span>
    </div>
    <button
      type="button"
      class="flex h-7 w-7 items-center justify-center rounded-full border transition-colors"
      :class="collab.micOn.value
        ? 'border-primary bg-primary/15 text-primary'
        : collab.micError.value
          ? 'border-destructive bg-card text-destructive'
          : 'border-border bg-card text-muted-foreground hover:text-foreground'"
      :title="micLabel"
      :aria-label="micLabel"
      :aria-pressed="collab.micOn.value"
      data-testid="collab-mic-toggle"
      @click="collab.toggleMic()"
    >
      <Mic
        v-if="collab.micOn.value"
        class="h-3.5 w-3.5"
      />
      <MicOff
        v-else
        class="h-3.5 w-3.5"
      />
    </button>
    <button
      v-if="collab.autoplayBlocked.value"
      type="button"
      class="flex h-7 items-center gap-1 rounded-full border border-border bg-card px-2.5 text-xs"
      @click="collab.resumeAudio()"
    >
      <Volume2 class="h-3.5 w-3.5" />
      Enable audio
    </button>
    <span
      v-if="collab.status.value !== 'open'"
      class="text-xs text-muted-foreground"
    >Reconnecting…</span>
  </div>
</template>
```

- [ ] **Step 3: Follow frame**

`frontend/src/features/collab/components/FollowFrame.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { X } from "lucide-vue-next";

import type { CollabUserView } from "@/features/collab/useCanvasCollab";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

const OWNER_DIALOG_LABELS: Record<string, string> = {
  share: "Share settings",
  curl: "cURL settings",
  portal: "Portal settings",
  template: "Share as template",
  editHistory: "Edit History",
};

const collab = useCollabContext();
const leader = computed<CollabUserView | null>(() => collab?.followedUser.value ?? null);
const dialogLabel = computed<string | null>(() => {
  const key = collab?.followedOwnerDialog.value;
  return key ? OWNER_DIALOG_LABELS[key] ?? null : null;
});
</script>

<template>
  <div
    v-if="collab && leader"
    class="pointer-events-none absolute inset-0 z-30 border-2"
    :style="{ borderColor: leader.color }"
    data-testid="collab-follow-frame"
  >
    <div
      class="pointer-events-auto absolute left-1/2 top-2 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-white shadow"
      :style="{ backgroundColor: leader.color }"
    >
      <span>
        Following {{ leader.name }}<template v-if="dialogLabel"> · in {{ dialogLabel }}</template> · Esc to stop
      </span>
      <button
        type="button"
        class="rounded-full p-0.5 hover:bg-black/20"
        aria-label="Stop following"
        @click="collab.stopFollowing()"
      >
        <X class="h-3 w-3" />
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Mount in EditorView**

In `frontend/src/views/EditorView.vue`:

1. Add imports next to the other component imports:

```ts
import CollabOverlay from "@/features/collab/components/CollabOverlay.vue";
import FollowFrame from "@/features/collab/components/FollowFrame.vue";
import { useCanvasCollab } from "@/features/collab/useCanvasCollab";
import { useEditorFollowSignals } from "@/features/collab/useEditorFollowSignals";
```

2. Directly after `const workflowId = computed(() => route.params.id as string);`:

```ts
// Canvas collaboration joins the room once this workflow is loaded.
const collabWorkflowId = computed<string | null>(() =>
  !loading.value && workflowStore.currentWorkflow?.id === workflowId.value ? workflowId.value : null,
);
useCanvasCollab(collabWorkflowId);
const portalOpen = computed<boolean>(() => portalDialogRef.value?.isOpen ?? false);
useEditorFollowSignals({
  rightPanelOpen,
  historyOpen,
  ownerDialogs: {
    share: shareOpen,
    curl: curlOpen,
    template: shareTemplateOpen,
    editHistory: editHistoryOpen,
    portal: portalOpen,
  },
});
```

If `workflowStore` is declared below line 135, move this block to just after `const workflowStore = useWorkflowStore();`, keeping it after `workflowId`, `loading`, the panel refs and `portalDialogRef`.

3. In the template, directly after `<WorkflowCanvas />` (inside the desktop `flex-1 relative` container):

```vue
          <CollabOverlay />
          <FollowFrame />
```

- [ ] **Step 5: Mount the bridge and cursors in WorkflowCanvas**

In `frontend/src/components/Canvas/WorkflowCanvas.vue`:

1. Imports:

```ts
import CollabCanvasBridge from "@/features/collab/CollabCanvasBridge";
import CollabCursors from "@/features/collab/components/CollabCursors.vue";
```

2. Inside `<VueFlow ...>`, after the `<Transition name="minimap-fade">...</Transition>` block and before `</VueFlow>`:

```vue
      <template #zoom-pane>
        <CollabCursors />
      </template>
      <CollabCanvasBridge />
```

- [ ] **Step 6: Lint, typecheck, unit tests, build**

Run: `cd frontend && bun run lint && bun run typecheck && bun run test && bun run build`
Expected: all pass.

---

### Task 17: Release tour

**Files:**
- Modify: `frontend/src/features/release-tour/releaseRegistry.ts`
- Create: `frontend/src/features/release-tour/components/visuals/CanvasCollaborationTourVisual.vue`
- Delete: `frontend/src/features/release-tour/components/visuals/HeymWorkTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`
- Modify: `frontend/src/features/release-tour/releaseTourMapper.test.ts`

The registry keeps only the five newest sections. Adding this one drops the oldest, `heym-work` (release `2026.19`), with its visual.

- [ ] **Step 1: Update the registry tests first**

In `releaseTourMapper.test.ts`, in `describe("shipped release registry", ...)`:
- In "lists every shipped tour, newest first", remove `"heym-work",` from the expected list. The new release has `tourEnabled: false`, so it is not in the catalog.
- In "registers a visual for every section, including unreleased ones", replace `expect(tours.map((tour) => tour.tourVisual)).toContain("heym-work");` with `expect(tours.map((tour) => tour.tourVisual)).toContain("canvas-collaboration");`.
- Delete the test "carries the Heym Work slide's link to heym.run".

Run: `cd frontend && bunx vitest run src/features/release-tour`
Expected: FAIL ("canvas-collaboration" missing, catalog still lists "heym-work").

- [ ] **Step 2: Registry entry**

In `releaseRegistry.ts`, delete the whole `releaseId: "2026.19"` entry and add this as the first element of `RELEASE_REGISTRY`:

```ts
  {
    releaseId: "2026.22",
    publishedAt: new Date("2026-10-25T12:00:00Z"),
    headline: "Work on one canvas together",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["canvas-collaboration"],
    },
    sections: [
      {
        id: "canvas-collaboration",
        title: "Work on a canvas together",
        publishedAt: new Date("2026-10-25T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Everyone who opens a workflow now shows as an avatar at the top left of the canvas. Edits reach every open canvas as they happen, and each person's pointer moves in their own color. Anyone with edit access can save the shared draft, and **Ctrl+Z** undoes only your own changes.",
          },
          {
            type: "prose",
            markdown:
              "Click an avatar to **follow** that person: your canvas shows what they look at, the dialogs they open and the runs they start, with your own access. Press **Esc** to stop. Turn on the **microphone** next to the avatars to talk with everyone on the canvas.",
          },
        ],
        tour: {
          description:
            "See who is on the canvas, edit together live, follow someone's view and talk with the microphone.",
          useCases: [
            "Build a workflow with a teammate without taking turns",
            "Walk someone through a run by letting them follow you",
            "Review a workflow together while talking it through",
          ],
          tourVisual: "canvas-collaboration",
          docTarget: {
            categoryId: "reference",
            slug: "canvas-collaboration",
            title: "Canvas Collaboration",
          },
        },
      },
    ],
  },
```

- [ ] **Step 3: Visual**

`CanvasCollaborationTourVisual.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import { Mic, MousePointer2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: two people on one canvas · 1: Ana adds a node, Ben sees it ·
// 2: Ben follows Ana · 3: Ana talks with the mic on.
const step = useCycleStep(4, 1800);

const nodeVisible = computed<boolean>(() => step.value >= 1);
const following = computed<boolean>(() => step.value === 2);
const talking = computed<boolean>(() => step.value === 3);
const anaCursor = computed<Record<string, string>>(() =>
  step.value === 0 ? { left: "24%", top: "64%" } : { left: "58%", top: "40%" },
);
const benCursor = computed<Record<string, string>>(() =>
  step.value >= 2 ? { left: "62%", top: "48%" } : { left: "74%", top: "72%" },
);
const caption = computed<string>(() => {
  if (step.value === 0) return "Everyone on the canvas, top left";
  if (step.value === 1) return "Edits show up for everyone";
  if (step.value === 2) return "Click an avatar to follow";
  return "Turn the mic on to talk";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 overflow-hidden rounded-lg bg-card p-3">
    <div
      class="relative min-h-0 flex-1 overflow-hidden rounded-md border-2 bg-background/60 transition-colors duration-500"
      :class="following ? 'border-primary' : 'border-transparent'"
    >
      <div class="absolute left-2 top-2 flex items-center gap-1.5">
        <div class="flex -space-x-1">
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[8px] font-semibold ring-2 ring-primary"
            :class="talking ? 'animate-pulse' : ''"
          >A</span>
          <span class="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[8px] font-semibold ring-2 ring-[hsl(var(--success))]">B</span>
        </div>
        <span
          class="flex h-5 w-5 items-center justify-center rounded-full border transition-colors duration-500"
          :class="talking ? 'border-primary bg-primary/15 text-primary' : 'border-border text-muted-foreground'"
        >
          <Mic class="h-2.5 w-2.5" />
        </span>
      </div>
      <span
        v-if="following"
        class="absolute left-1/2 top-2 -translate-x-1/2 rounded-full bg-primary px-1.5 py-0.5 text-[8px] font-medium text-primary-foreground"
      >Following Ana · Esc</span>
      <div class="absolute left-[12%] top-[46%] rounded-md border border-border bg-card px-1.5 py-1 text-[9px]">
        Webhook
      </div>
      <div
        class="absolute left-[48%] top-[28%] rounded-md border border-primary/60 bg-card px-1.5 py-1 text-[9px] transition-all duration-500"
        :class="nodeVisible ? 'scale-100 opacity-100' : 'scale-75 opacity-0'"
      >
        Agent
      </div>
      <div
        class="absolute flex items-start transition-all duration-700 ease-out"
        :style="anaCursor"
      >
        <MousePointer2 class="h-3 w-3 fill-primary text-primary" />
        <span class="ml-0.5 mt-2 rounded bg-primary px-1 text-[7px] text-primary-foreground">Ana</span>
      </div>
      <div
        class="absolute flex items-start transition-all duration-700 ease-out"
        :style="benCursor"
      >
        <MousePointer2 class="h-3 w-3 fill-[hsl(var(--success))] text-[hsl(var(--success))]" />
        <span class="ml-0.5 mt-2 rounded bg-[hsl(var(--success))] px-1 text-[7px] text-white">Ben</span>
      </div>
    </div>
    <p class="text-center text-[10px] leading-none text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
```

- [ ] **Step 4: Register it, drop the Heym Work visual**

In `tourVisuals.ts`: remove the `HeymWorkTourVisual` import and its `"heym-work"` entry, then add:

```ts
import CanvasCollaborationTourVisual from "@/features/release-tour/components/visuals/CanvasCollaborationTourVisual.vue";
```

and the entry:

```ts
  "canvas-collaboration": CanvasCollaborationTourVisual,
```

Delete the file: `rm frontend/src/features/release-tour/components/visuals/HeymWorkTourVisual.vue`. Then check nothing else imports it: `grep -rn "HeymWorkTourVisual" frontend/src` (expect no output).

- [ ] **Step 5: Run the tour tests**

Run: `cd frontend && bunx vitest run src/features/release-tour && bun run lint && bun run typecheck`
Expected: pass. `frontend/e2e/support.ts` stays as is: the new release is not enabled.

---

### Task 18: Docs

**Files:**
- Create: `frontend/src/docs/content/reference/canvas-collaboration.md`
- Modify: `frontend/src/docs/manifest.ts`
- Modify: `frontend/src/docs/content/reference/features.md`
- Modify: `frontend/src/docs/content/reference/canvas-features.md`
- Modify: `frontend/src/docs/content/reference/keyboard-shortcuts.md`

If a `heym-documentation` skill is available, load it first and follow its conventions; the content below is the substance.

- [ ] **Step 1: The page**

`canvas-collaboration.md`:

```markdown
# Canvas Collaboration

Everyone who opens the same workflow sees the others on the canvas and works on one shared draft. Edits show up for everyone as they happen, each person's pointer moves in their own color, you can follow what someone else is looking at, and you can talk with the microphone.

## Who is on the canvas

The avatars at the top left of the canvas show everyone who has the workflow open, including you. Each person has a color: their avatar ring, their pointer and the frame you see while following them all use it. Hover an avatar to see the name and whether that person can edit or only view. More than five people show as **+N**.

## Editing together

People with edit access change the same draft. Adding, deleting, moving and connecting nodes, and changing node settings, reach every open canvas within a moment, without saving first.

- **Saving.** Anyone with edit access can save. The save stores the shared draft, and **Unsaved changes** clears for everyone whose canvas matches what was saved.
- **Same setting, same moment.** When two people change the same node's settings at the same time, the change that reaches the server last wins on every screen. Moving a node and editing its settings never overwrite each other.
- **Undo.** **Ctrl+Z** undoes only your own changes. Changes made by others stay.
- **Joining later.** If someone already has unsaved changes, a canvas that opens the workflow later starts from that draft, not from the last save.
- **View-only access.** People who can only view see every change live but cannot edit. If the last person with edit access leaves without saving, the unsaved changes are discarded and view-only canvases return to the saved version.
- **Saved elsewhere.** When the workflow is saved outside the canvas (from the Chat tab, over MCP, or by restoring a version in [Edit History](./edit-history.md)), canvases without unsaved changes load the new version. With unsaved changes, editors choose between loading the saved version for everyone and keeping the draft.

## Pointers

Each person's pointer appears on your canvas with their name, over the same node they point at, whatever your zoom.

## Following someone

Click someone's avatar to follow them. Your canvas then shows:

- the part of the canvas they look at, and where they point
- the node they select, the properties panel and its tab
- the expression dialog they open
- the Debug panel and the execution they open in History
- a run they start, live on your canvas

Everything is shown with your own access. When they open a settings dialog only they can use, such as Share or Portal, the label at the top names it instead. A frame in their color marks that you are following.

To stop, press **Esc**, move the canvas yourself, or click their avatar again.

## Talking

Click the microphone next to the avatars to talk with everyone on the canvas. The first time, the browser asks for microphone access. You can hear others without turning on your own microphone. The ring of whoever is talking pulses.

Audio goes directly between browsers. It works on the same network, over a VPN, and across most home and office networks. If two people cannot connect, a red dot appears on the avatar. If the browser holds back sound until you interact with the page, an **Enable audio** button appears.

For administrators: to find a direct route, browsers contact the public STUN servers `stun.cloudflare.com` and `stun.l.google.com`. Audio never passes through them or through Heym. Without internet access, people on the same network or VPN still connect.

## Where it works

Pointers, following and talking are available in the desktop editor. The mobile editor receives live edits.
```

- [ ] **Step 2: Register it**

In `frontend/src/docs/manifest.ts`, after `{ slug: "canvas-features", title: "Canvas Features" },` add:

```ts
      { slug: "canvas-collaboration", title: "Canvas Collaboration" },
```

- [ ] **Step 3: Feature list**

In `features.md`, after the `### [Canvas Features](./canvas-features.md)` section (before `### [Keyboard Shortcuts](./keyboard-shortcuts.md)`), add:

```markdown
### [Canvas Collaboration](./canvas-collaboration.md)

Everyone who opens a workflow appears as an avatar at the top left of the canvas. Edits reach every open canvas live, each person's pointer shows in their color, clicking an avatar follows that person's view, dialogs and runs, and the microphone toggle lets people talk to each other directly from the browser.

See also [Canvas Features](./canvas-features.md) and [Edit History](./edit-history.md).
```

- [ ] **Step 4: Canvas features and shortcuts**

At the end of `canvas-features.md` add:

```markdown
## Working Together

Everyone who opens the workflow appears at the top left of the canvas, edits reach every open canvas live, and you can follow someone or talk with them. See [Canvas Collaboration](./canvas-collaboration.md).
```

In `keyboard-shortcuts.md`, in the canvas table, after the row ``| `Escape` | Deselect all nodes; close inline node search |`` add:

```markdown
| `Escape` | Stop following someone ([Canvas Collaboration](./canvas-collaboration.md)) |
```

- [ ] **Step 5: Verify**

Run: `cd frontend && bun run lint && bun run typecheck && grep -c "—" src/docs/content/reference/canvas-collaboration.md`
Expected: lint and typecheck pass; the em-dash count is `0`.

---

### Task 19: README and the feature showcase SVG

**Files:**
- Modify: `README.md`
- Modify: `docs/readme-assets/full-feature-showcase.svg`
- Scratch: `<scratchpad>/add_collab_scene.py` (not in the repo)

- [ ] **Step 1: Write the SVG script to the scratchpad**

`<scratchpad>/add_collab_scene.py`:

```python
"""Add scene 21 (real-time collaboration) to the README full feature showcase.

Scenes are 5 s each; 21 scenes make a 105 s loop. Keyframe percentages are rescaled by
100/105 and scene-bound delays are recomputed so every scene keeps its slot.
"""

import sys
from pathlib import Path

path = Path(sys.argv[1])
svg = path.read_text()


def replace_once(old: str, new: str) -> None:
    global svg
    count = svg.count(old)
    if count != 1:
        raise SystemExit(f"expected one match, found {count}: {old!r}")
    svg = svg.replace(old, new)


# Scene-bound helpers first (their old delays collide with new scene delays).
replace_once(
    "ffSSE 100s linear infinite both; animation-delay: -45s; }",
    "ffSSE 105s linear infinite both; animation-delay: -50s; }",
)
for old, new in (
    ("44.7", "49.7"), ("44.4", "49.4"), ("44.1", "49.1"), ("43.8", "48.8"),
    ("43.5", "48.5"), ("43.2", "48.2"), ("42.9", "47.9"), ("42.6", "47.6"),
):
    replace_once(f"{{ animation-delay: -{old}s; }}", f"{{ animation-delay: -{new}s; }}")
replace_once(
    "ffKbnMove 100s linear infinite both; animation-delay: -5s; }",
    "ffKbnMove 105s linear infinite both; animation-delay: -10s; }",
)
replace_once(
    "ffKbnFill 100s linear infinite both; animation-delay: -5s; }",
    "ffKbnFill 105s linear infinite both; animation-delay: -10s; }",
)
replace_once("animation: ffProgress 100s", "animation: ffProgress 105s")
replace_once("animation: ffScene 100s", "animation: ffScene 105s")

for n in range(2, 21):
    replace_once(
        f".ff-scene.s{n:02d} {{ animation-delay: -{100 - 5 * (n - 1)}s; }}",
        f".ff-scene.s{n:02d} {{ animation-delay: -{105 - 5 * (n - 1)}s; }}",
    )
replace_once(
    ".ff-scene.s20 { animation-delay: -10s; }",
    ".ff-scene.s20 { animation-delay: -10s; }\n      .ff-scene.s21 { animation-delay: -5s; }",
)

for old, new in (
    ("0%, 4.37% { opacity: 1; transform: translateY(0); }", "0%, 4.16% { opacity: 1; transform: translateY(0); }"),
    ("\n        5% { opacity: 0; transform: translateY(10px); }", "\n        4.76% { opacity: 0; transform: translateY(10px); }"),
    ("5.001%, 100% { opacity: 0; transform: translateY(10px); }", "4.77%, 100% { opacity: 0; transform: translateY(10px); }"),
    ("0.3% { opacity: 1; }", "0.29% { opacity: 1; }"),
    ("\n        5% { opacity: 1; }", "\n        4.76% { opacity: 1; }"),
    ("5.001%, 100% { opacity: 0; }", "4.77%, 100% { opacity: 0; }"),
    ("0%, 0.7% { transform: translateX(0); }", "0%, 0.67% { transform: translateX(0); }"),
    ("1.6%, 2.4% { transform: translateX(163px); }", "1.52%, 2.29% { transform: translateX(163px); }"),
    ("3.3%, 4.37% { transform: translateX(326px); }", "3.14%, 4.16% { transform: translateX(326px); }"),
    ("4.38%, 100% { transform: translateX(0); }", "4.17%, 100% { transform: translateX(0); }"),
    ("0%, 1.3% { fill: #0A0E1A;", "0%, 1.24% { fill: #0A0E1A;"),
    ("1.7%, 2.5% { fill: rgba(245,158,11,0.16);", "1.62%, 2.38% { fill: rgba(245,158,11,0.16);"),
    ("3.3%, 100% { fill: rgba(16,217,160,0.16);", "3.14%, 100% { fill: rgba(16,217,160,0.16);"),
):
    replace_once(old, new)

replace_once(
    ".ff-logo-mark { stroke-dasharray: 10 6; animation: ffLogoDash 2.4s linear infinite; }",
    ".ff-logo-mark { stroke-dasharray: 10 6; animation: ffLogoDash 2.4s linear infinite; }\n"
    "      .ff-cur-a { animation: ffCurA 3.4s ease-in-out infinite; }\n"
    "      .ff-cur-b { animation: ffCurB 3.4s ease-in-out infinite; }",
)
replace_once(
    "@keyframes ffLogoDash { to { stroke-dashoffset: -32; } }",
    "@keyframes ffLogoDash { to { stroke-dashoffset: -32; } }\n"
    "      @keyframes ffCurA {\n"
    "        0%, 100% { transform: translate(330px, 168px); }\n"
    "        50% { transform: translate(372px, 120px); }\n"
    "      }\n"
    "      @keyframes ffCurB {\n"
    "        0%, 100% { transform: translate(140px, 176px); }\n"
    "        50% { transform: translate(214px, 150px); }\n"
    "      }",
)

dots_open = '<g fill="#374151">'
if svg.count(dots_open) != 1:
    raise SystemExit("progress dots group not found exactly once")
start = svg.index(dots_open)
end = svg.index("</g>", start)
dots = "".join(
    f'\n      <circle cx="{1152 * i / 20:g}" cy="1.5" r="3"></circle>' for i in range(21)
)
svg = svg[:start] + dots_open + dots + "\n    " + svg[end:]

MONO = "&#39;JetBrains Mono&#39;,monospace"
SCENE = f"""    <g class="ff-scene s21">
      <text font-size="11" font-family="&#39;JetBrains Mono&#39;, monospace" fill="#22D3EE" letter-spacing="2">21 · REAL-TIME COLLABORATION</text>
      <text y="64" font-size="64" font-weight="800" fill="#F3F4F6" letter-spacing="-2">Build it.</text>
      <text y="124" font-size="64" font-weight="800" fill="#22D3EE" letter-spacing="-2">Together.</text>
      <text y="172" font-size="16" fill="#9CA3AF">Live cursors · shared edits · follow mode · voice on one canvas.</text>
      <g transform="translate(620,36)">
        <rect width="500" height="216" rx="14" fill="#0B1020" stroke="#1F2937"></rect>
        <rect x="6" y="6" width="488" height="204" rx="10" fill="none" stroke="#F59E0B" stroke-opacity="0.6" stroke-width="1.5" class="ff-flow"></rect>
        <g transform="translate(26,28)">
          <circle class="ff-pulse" cx="0" cy="0" r="11" fill="#1F2937" stroke="#F59E0B" stroke-width="2"></circle>
          <text x="0" y="4" font-size="10" font-weight="700" fill="#F3F4F6" text-anchor="middle">A</text>
          <circle cx="20" cy="0" r="11" fill="#1F2937" stroke="#22D3EE" stroke-width="2"></circle>
          <text x="20" y="4" font-size="10" font-weight="700" fill="#F3F4F6" text-anchor="middle">B</text>
          <circle cx="40" cy="0" r="11" fill="#1F2937" stroke="#A78BFA" stroke-width="2"></circle>
          <text x="40" y="4" font-size="10" font-weight="700" fill="#F3F4F6" text-anchor="middle">C</text>
          <circle cx="68" cy="0" r="11" fill="#10D9A0" fill-opacity="0.14" stroke="#10D9A0"></circle>
          <rect x="65" y="-6" width="6" height="9" rx="3" fill="#10D9A0"></rect>
          <path d="M 62.5 1 Q 68 7 73.5 1 M 68 5 L 68 8" stroke="#10D9A0" stroke-width="1.2" fill="none"></path>
        </g>
        <g transform="translate(318,19)" font-family="{MONO}" font-size="9">
          <rect width="160" height="18" rx="5" fill="#F59E0B" fill-opacity="0.16" stroke="#F59E0B" stroke-opacity="0.55"></rect>
          <text x="10" y="12.5" fill="#F59E0B">following Ana · esc to stop</text>
        </g>
        <g transform="translate(56,112)">
          <rect width="116" height="40" rx="9" fill="#0F1526" stroke="#2A3446"></rect>
          <text x="14" y="25" font-size="11" fill="#E5E7EB" font-family="{MONO}">Webhook</text>
        </g>
        <path d="M 172 132 L 272 132" stroke="#22D3EE" stroke-width="1.6" class="ff-flow" fill="none"></path>
        <g transform="translate(272,112)">
          <rect width="124" height="40" rx="9" fill="#7C3AED" fill-opacity="0.14" stroke="#A78BFA" stroke-opacity="0.7"></rect>
          <text x="14" y="25" font-size="11" fill="#A78BFA" font-family="{MONO}">Agent</text>
          <circle class="ff-pulse" cx="112" cy="12" r="3.5" fill="#F59E0B"></circle>
        </g>
        <g class="ff-cur-a">
          <path d="M 0 0 L 14 6 L 7.5 8 L 5 15 Z" fill="#F59E0B" stroke="#0B1020" stroke-width="1"></path>
          <rect x="12" y="13" width="32" height="15" rx="4" fill="#F59E0B"></rect>
          <text x="17" y="24" font-size="9" font-weight="700" fill="#0B1020">Ana</text>
        </g>
        <g class="ff-cur-b">
          <path d="M 0 0 L 14 6 L 7.5 8 L 5 15 Z" fill="#22D3EE" stroke="#0B1020" stroke-width="1"></path>
          <rect x="12" y="13" width="32" height="15" rx="4" fill="#22D3EE"></rect>
          <text x="17" y="24" font-size="9" font-weight="700" fill="#0B1020">Ben</text>
        </g>
      </g>
    </g>

"""
footer = '<g transform="translate(64,680)"'
scenes_end = svg.rindex("  </g>", 0, svg.index(footer))
svg = svg[:scenes_end] + SCENE + svg[scenes_end:]

path.write_text(svg)
print("scene 21 added")
```

- [ ] **Step 2: Run it and validate**

Run (from the repo root):

```bash
python3 <scratchpad>/add_collab_scene.py docs/readme-assets/full-feature-showcase.svg
python3 -c "import xml.dom.minidom; xml.dom.minidom.parse('docs/readme-assets/full-feature-showcase.svg'); print('well-formed')"
grep -c 'class="ff-scene s' docs/readme-assets/full-feature-showcase.svg
grep -c '100s' docs/readme-assets/full-feature-showcase.svg
```

Expected: `scene 21 added`, `well-formed`, `21`, `0`. Then open the SVG in a browser and watch the loop around 1:35 to 1:45 to confirm scene 20 hands over to scene 21 and back to scene 1.

- [ ] **Step 3: README text**

In `README.md`, in `## Build and Orchestrate`, after the `workflow-canvas.svg` `<div>` block and before `### AI Assistant`, add:

```markdown
### Real-time Collaboration

Open the same workflow with your team and work on it together. Everyone on the canvas shows as an avatar at the top left, pointers move in each person's color, and edits reach every open canvas as they happen. Click an avatar to follow what that person sees, including the dialogs they open and the runs they start, and turn on the microphone to talk directly from the browser.
```

In `## Documentation and Full Feature Set`, change the opening sentence's list `(Expression DSL, workflow structure, webhooks, SSE streaming, AI Assistant, Chat with Docs, Portal, security, etc.)` to `(Expression DSL, workflow structure, real-time canvas collaboration, webhooks, SSE streaming, AI Assistant, Chat with Docs, Portal, security, etc.)`.

---

### Task 20: Full verification and manual smoke test

- [ ] **Step 1: Backend suite and lint**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`
Expected: frontend lint/typecheck, backend ruff and backend tests pass. Known local-only failures are listed in memory (egress tests from `.env`, two Postgres flakes); anything else must be fixed.

- [ ] **Step 2: Frontend tests and build**

Run: `cd frontend && bun run test && bun run build`
Expected: pass.

- [ ] **Step 3: Manual smoke test (two browsers)**

Start `./run.sh`. User A (owner) in Chrome; user B (read share) in a second profile or Firefox. Open the same workflow.
1. Both avatars appear top left, with ring colors. Hover shows name and access.
2. Move the mouse on A: B sees A's cursor with the name; zoom B: the cursor stays over the same node.
3. A adds a node, drags it, edits a prompt: B sees all three live. B (read) cannot edit.
4. Give B write access (Share), reload B. Both edit different nodes, then the same field at the same moment: both end on one value.
5. A presses Ctrl+Z: only A's last change reverts.
6. A saves: B's "Unsaved changes" clears. B saves right after: no conflict dialog.
7. Save the workflow from the Chat tab (build mode) while both are clean: both reload. Repeat with an unsaved edit: A gets the stale dialog; "Reload" reloads both.
8. B clicks A's avatar: B follows A's pan/zoom, selection, properties tab, an expression dialog, the Debug panel and History. A opens Share: B's frame says "in Share settings". A runs the workflow: B sees nodes light up. Esc stops following.
9. A turns the mic on (permission prompt), B hears A without turning its own mic on; A's ring pulses when talking. B turns its mic on: two-way audio. Close B's tab: A's link closes.
10. Check the browser network tab: one WebSocket per canvas; with one person on the canvas it only carries heartbeats.

- [ ] **Step 4: Leave the diff**

Run: `git status --short`
Expected: the files in the file map, uncommitted. Do not commit or push.

---

## Deviations found while implementing (2026-10-25)

- **`app/api/collab.py` session structure.** Receiving runs on the request's own task; the send and permission-recheck loops are helper tasks that set a shared `closed` event before they close the socket. Waiting on all three with `asyncio.wait` let a cancellation escape when the client went away (Starlette's TestClient cancels the app right after the disconnect), so four socket tests failed with `CancelledError`.
- **Esc stops following through `onDismissOverlays`.** The app's `useOverlayBackHandler` listens for Escape on `window` in the capture phase and stops propagation, so a plain `keydown` listener never fires. With the overlay handler, an open dialog closes first and the next Esc stops following, like every other overlay.
- **`tests/test_workflow_update_websocket_sync.py`** gained a third `db.execute` result: its mock answers a fixed list and the save now queues one more statement (the `saved` NOTIFY).
- **Release tour test.** Instead of deleting "carries the Heym Work slide's link", the external-link mapping is covered by a fixture test in `buildTourSlides`.
- **SVG check.** `grep -c '100s'` is 1 after the script, not 0: scene 2's new delay is `-100s`. No loop duration stays at 100 s.
- **Smoke test.** Ran as a throwaway Playwright probe on the isolated E2E stack (two browser contexts, one read share, fake media device for the mic): presence, cursor, live drag, save clearing the peer's marker, follow frame with the owner-dialog label, Esc, leave, and a WebRTC connection reaching `connected`. The probe was deleted afterwards.
