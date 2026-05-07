"""Short-lived MCP SSE session tokens.

When a client connects to the SSE endpoint it is issued a short-lived signed
session token that is embedded in the message endpoint URL instead of the
actual MCP API key or OAuth bearer token. This avoids leaking long-lived
credentials in server access logs while still working across multiple backend
workers.
"""

import asyncio
import secrets
import threading
import time
from dataclasses import dataclass, field

import jwt
from jwt import InvalidTokenError

from app.config import settings

_SESSION_TTL_SECONDS = 3600  # 1 hour
_CLEANUP_INTERVAL_SECONDS = 600
_TOKEN_TYPE = "mcp_sse_session"


@dataclass
class _MCPSession:
    user_id: str
    created_at: float
    server_id: str | None = field(default=None)


class MCPSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _MCPSession] = {}
        self._revoked_jtis: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < _CLEANUP_INTERVAL_SECONDS:
            return
        expired = [
            k for k, s in self._sessions.items() if now - s.created_at > _SESSION_TTL_SECONDS
        ]
        for k in expired:
            del self._sessions[k]
        expired_jtis = [k for k, expires_at in self._revoked_jtis.items() if expires_at <= now]
        for k in expired_jtis:
            del self._revoked_jtis[k]
        self._last_cleanup = now

    def create(self, user_id: str, server_id: str | None = None) -> str:
        """Create a signed session token mapped to user_id (and optionally server_id)."""
        now = time.time()
        expires_at = now + _SESSION_TTL_SECONDS
        payload = {
            "sub": user_id,
            "type": _TOKEN_TYPE,
            "jti": secrets.token_urlsafe(16),
            "exp": int(expires_at),
        }
        if server_id is not None:
            payload["sid"] = server_id
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        with self._lock:
            self._cleanup(now)
        return token

    def resolve(self, token: str) -> tuple[str, str | None] | None:
        """Return (user_id, server_id) for a valid non-expired token, or None."""
        now = time.time()
        with self._lock:
            self._cleanup(now)
            try:
                payload = jwt.decode(
                    token, settings.secret_key, algorithms=[settings.jwt_algorithm]
                )
            except InvalidTokenError:
                payload = None

            if payload is not None:
                jti = payload.get("jti")
                if payload.get("type") != _TOKEN_TYPE or not isinstance(jti, str):
                    return None
                if jti in self._revoked_jtis:
                    return None
                user_id = payload.get("sub")
                server_id = payload.get("sid")
                if not isinstance(user_id, str):
                    return None
                if server_id is not None and not isinstance(server_id, str):
                    return None
                return user_id, server_id

            session = self._sessions.get(token)
            if session is None:
                return None
            if now - session.created_at > _SESSION_TTL_SECONDS:
                del self._sessions[token]
                return None
            return session.user_id, session.server_id

    def revoke(self, token: str) -> None:
        with self._lock:
            try:
                payload = jwt.decode(
                    token, settings.secret_key, algorithms=[settings.jwt_algorithm]
                )
            except InvalidTokenError:
                payload = None
            if payload is not None:
                jti = payload.get("jti")
                exp = payload.get("exp")
                if isinstance(jti, str) and isinstance(exp, (int, float)):
                    self._revoked_jtis[jti] = float(exp)
                return
            self._sessions.pop(token, None)


mcp_session_store = MCPSessionStore()


class MCPSSEChannelStore:
    """In-memory response channels for legacy MCP SSE sessions."""

    def __init__(self) -> None:
        self._channels: dict[str, asyncio.Queue[str]] = {}
        self._lock = threading.Lock()

    def can_register(self) -> bool:
        """Return whether the process can accept another legacy SSE session."""
        max_sessions = settings.mcp_sse_max_sessions
        if max_sessions <= 0:
            return True
        with self._lock:
            return len(self._channels) < max_sessions

    def register(self, token: str) -> asyncio.Queue[str]:
        """Register an SSE response queue for a session token."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        with self._lock:
            max_sessions = settings.mcp_sse_max_sessions
            if max_sessions > 0 and len(self._channels) >= max_sessions:
                raise RuntimeError("Too many active MCP SSE sessions")
            self._channels[token] = queue
        return queue

    def exists(self, token: str) -> bool:
        """Return whether an SSE response queue is active for a token."""
        with self._lock:
            return token in self._channels

    async def send(self, token: str, payload: str) -> bool:
        """Send a payload to the active SSE response queue for a token."""
        with self._lock:
            queue = self._channels.get(token)
        if queue is None:
            return False
        await queue.put(payload)
        return True

    def unregister(self, token: str) -> None:
        """Remove the SSE response queue for a session token."""
        with self._lock:
            self._channels.pop(token, None)


mcp_sse_channels = MCPSSEChannelStore()
