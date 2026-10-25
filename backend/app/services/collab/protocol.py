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
    {"presence", "cursor", "ops", "sync_req", "snapshot", "reload", "signal", "assistant", "ui"}
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
