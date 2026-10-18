"""What an MCP client declared, and URL-mode elicitation (MCP 2025-11-25).

Heym's MCP endpoints keep no session, so what a client declared in `initialize` comes back
on every later request: in the signed `Mcp-Session-Id` header Heym hands out on Streamable
HTTP, or on the SSE channel of the legacy transport. A tool call that needs a secret sends
the client a URL-mode `elicitation/create`: the user opens a Heym page in the browser and
types the secret there, so it never passes through the client or the model. Form mode is
never used for secrets; the spec forbids it.
"""

import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import InvalidTokenError

from app.config import settings

LATEST_PROTOCOL_VERSION = "2025-11-25"
FALLBACK_PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = frozenset(
    {"2024-11-05", "2025-03-26", "2025-06-18", LATEST_PROTOCOL_VERSION}
)

FORM_MODE = "form"
URL_MODE = "url"
MCP_SESSION_HEADER = "Mcp-Session-Id"

_SESSION_TOKEN_TYPE = "mcp_client_session"
# Heym's own JSON-RPC ids for elicitation requests, so a client's reply finds its request.
_ELICITATION_ID_PREFIX = "heym-elicit-"
_REPLY_ACTIONS = frozenset({"accept", "decline", "cancel"})


def negotiate_protocol_version(requested: object) -> str:
    """Answer with the client's version when Heym speaks it.

    A newer version than Heym knows gets Heym's latest. Anything else keeps the version
    every client got before negotiation existed.
    """
    if isinstance(requested, str):
        if requested in SUPPORTED_PROTOCOL_VERSIONS:
            return requested
        if requested > LATEST_PROTOCOL_VERSION:
            return LATEST_PROTOCOL_VERSION
    return FALLBACK_PROTOCOL_VERSION


def elicitation_modes(capabilities: object) -> frozenset[str]:
    """The elicitation modes a client declared in `initialize`.

    An empty `elicitation` object means form mode only, for backwards compatibility.
    """
    if not isinstance(capabilities, dict):
        return frozenset()
    elicitation = capabilities.get("elicitation")
    if not isinstance(elicitation, dict):
        return frozenset()
    modes = frozenset(mode for mode in (FORM_MODE, URL_MODE) if mode in elicitation)
    return modes or frozenset({FORM_MODE})


def encode_client_session(
    *, user_id: uuid.UUID, server_id: uuid.UUID | None, modes: frozenset[str]
) -> str:
    """Sign what a client declared into the `Mcp-Session-Id` it sends back on each request.

    It grants nothing: every request still authenticates with its own credential.
    """
    payload: dict[str, Any] = {
        "type": _SESSION_TOKEN_TYPE,
        "sub": str(user_id),
        "jti": secrets.token_urlsafe(12),
        "elicitation": sorted(modes),
    }
    if server_id is not None:
        payload["sid"] = str(server_id)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_client_session(
    token: str | None, *, user_id: uuid.UUID, server_id: uuid.UUID | None
) -> frozenset[str]:
    """Elicitation modes from a session id Heym issued to this user on this server."""
    if not token:
        return frozenset()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        return frozenset()
    if payload.get("type") != _SESSION_TOKEN_TYPE or payload.get("sub") != str(user_id):
        return frozenset()
    if payload.get("sid") != (str(server_id) if server_id is not None else None):
        return frozenset()
    modes = payload.get("elicitation")
    if not isinstance(modes, list):
        return frozenset()
    return frozenset(mode for mode in modes if mode in (FORM_MODE, URL_MODE))


@dataclass(frozen=True)
class MCPClientChannel:
    """The client behind one tool call: what it supports and how to reach it mid-call."""

    elicitation_modes: frozenset[str]
    send: Callable[[dict[str, Any]], Awaitable[None]]

    @property
    def supports_url_elicitation(self) -> bool:
        return URL_MODE in self.elicitation_modes


def url_elicitation_request(elicitation_id: uuid.UUID, url: str, message: str) -> dict[str, Any]:
    """The `elicitation/create` request that asks the client to open `url`."""
    return {
        "jsonrpc": "2.0",
        "id": f"{_ELICITATION_ID_PREFIX}{elicitation_id}",
        "method": "elicitation/create",
        "params": {
            "mode": URL_MODE,
            "elicitationId": str(elicitation_id),
            "url": url,
            "message": message,
        },
    }


def elicitation_complete_notification(elicitation_id: uuid.UUID) -> dict[str, Any]:
    """Tells the client the interaction behind `elicitation_id` is done."""
    return {
        "jsonrpc": "2.0",
        "method": "notifications/elicitation/complete",
        "params": {"elicitationId": str(elicitation_id)},
    }


def is_client_response(body: object) -> bool:
    """Whether a POSTed message is the client's reply to a request Heym sent it."""
    return (
        isinstance(body, dict)
        and "method" not in body
        and "id" in body
        and ("result" in body or "error" in body)
    )


@dataclass(frozen=True)
class ElicitationReply:
    """The client's answer to one URL elicitation.

    `accept` only means the user agreed to open the page; `error` means the client could
    not show the request.
    """

    elicitation_id: uuid.UUID
    action: str


def parse_elicitation_reply(body: dict[str, Any]) -> ElicitationReply | None:
    """Read a client reply to one of Heym's elicitation requests, or None for any other."""
    raw_id = body.get("id")
    if not isinstance(raw_id, str) or not raw_id.startswith(_ELICITATION_ID_PREFIX):
        return None
    try:
        elicitation_id = uuid.UUID(raw_id[len(_ELICITATION_ID_PREFIX) :])
    except ValueError:
        return None
    if "error" in body:
        return ElicitationReply(elicitation_id, "error")
    result = body.get("result")
    action = result.get("action") if isinstance(result, dict) else None
    if action not in _REPLY_ACTIONS:
        return None
    return ElicitationReply(elicitation_id, str(action))
