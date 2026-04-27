"""Short-lived MCP SSE session tokens.

When a client connects to the SSE endpoint it is issued a short-lived,
single-use session token that is embedded in the message endpoint URL
instead of the actual MCP API key or OAuth bearer token.  This avoids
leaking long-lived credentials in server access logs.
"""

import secrets
import threading
import time
from dataclasses import dataclass

_SESSION_TTL_SECONDS = 3600  # 1 hour
_CLEANUP_INTERVAL_SECONDS = 600


@dataclass
class _MCPSession:
    user_id: str
    created_at: float


class MCPSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _MCPSession] = {}
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
        self._last_cleanup = now

    def create(self, user_id: str) -> str:
        """Create a new session token mapped to user_id."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._cleanup(now)
            self._sessions[token] = _MCPSession(user_id=user_id, created_at=now)
        return token

    def resolve(self, token: str) -> str | None:
        """Return user_id for a valid, non-expired session token, or None."""
        now = time.time()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if now - session.created_at > _SESSION_TTL_SECONDS:
                del self._sessions[token]
                return None
            return session.user_id

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)


mcp_session_store = MCPSessionStore()
