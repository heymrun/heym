"""Execution tokens for Playwright AI step callbacks from subprocess.

Uses JWT signed with SECRET_KEY so tokens are stateless and valid across
all uvicorn workers without any shared state. Besides the user, the token carries
the run's workflow, node and LLM session so the callback can record its LLM trace
against the node that made it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

from app.config import settings

_TTL_SECONDS = 600  # 10 minutes
_TOKEN_TYPE = "playwright_execution"


@dataclass(frozen=True)
class PlaywrightExecutionClaims:
    """Who and what a Playwright AI step callback runs for."""

    user_id: str
    workflow_id: str | None = None
    node_id: str | None = None
    node_label: str | None = None
    session_id: str | None = None


def create_token(
    user_id: str,
    *,
    workflow_id: str | None = None,
    node_id: str | None = None,
    node_label: str | None = None,
    session_id: str | None = None,
) -> str:
    """Create a signed JWT execution token for Playwright subprocess callbacks."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=_TTL_SECONDS)
    payload: dict[str, object] = {
        "sub": user_id,
        "exp": expire,
        "type": _TOKEN_TYPE,
    }
    optional_claims = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "node_label": node_label,
        "session_id": session_id,
    }
    payload.update({key: value for key, value in optional_claims.items() if value})
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def _optional_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def validate_token(token: str | None) -> PlaywrightExecutionClaims | None:
    """Validate token and return its claims if valid, else None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        return None
    if payload.get("type") != _TOKEN_TYPE:
        return None
    user_id = _optional_str(payload, "sub")
    if user_id is None:
        return None
    return PlaywrightExecutionClaims(
        user_id=user_id,
        workflow_id=_optional_str(payload, "workflow_id"),
        node_id=_optional_str(payload, "node_id"),
        node_label=_optional_str(payload, "node_label"),
        session_id=_optional_str(payload, "session_id"),
    )
