"""Structured audit trail for security-relevant actions.

Records are emitted through the ``winston.audit`` logger as single, self-contained
lines on stdout, so they reach the Logs tab alongside the access log while staying
separable from it (``grep "[winston.audit]"``). Nothing is written to the database.

Callers pass identifiers, names, and counts only. ``_redact`` is a safety net for a
caller mistake, not the primary defence: a secret value must never be handed to
``audit()`` in the first place.

Client IPs are deliberately absent. Behind a load balancer they are either the
proxy's own address or a spoofable forwarded header, so they identify the user
without reliably identifying anything else.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.db.models import User

logger = logging.getLogger("winston.audit")

# Any detail key containing one of these loses its value. Over-redaction is
# deliberate: an unhelpful line beats a leaked credential.
_SENSITIVE_KEY_PARTS = (
    "password",
    "passphrase",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "authorization",
    "cookie",
    "credential_data",
    "value",
)

_REDACTED = "***"
_MAX_VALUE_LEN = 256

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_DENIED = "denied"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if len(text) > _MAX_VALUE_LEN:
        text = text[:_MAX_VALUE_LEN] + "...(truncated)"
    if text == "" or any(char in text for char in ' ="') or "\n" in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        return f'"{escaped}"'
    return text


def _render(pairs: list[tuple[str, Any]]) -> str:
    return " ".join(f"{key}={_format_value(value)}" for key, value in pairs if value is not None)


def audit(
    *,
    action: str,
    actor: User | None = None,
    outcome: str = OUTCOME_SUCCESS,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    target_name: str | None = None,
    actor_id: uuid.UUID | str | None = None,
    actor_email: str | None = None,
    **detail: Any,
) -> None:
    """Emit one audit line. Never raises, never blocks, never touches the database."""
    try:
        resolved_actor_id = actor.id if actor is not None else actor_id
        resolved_actor_email = actor.email if actor is not None else actor_email

        pairs: list[tuple[str, Any]] = [
            ("action", action),
            ("outcome", outcome),
            ("actor_id", resolved_actor_id),
            ("actor_email", resolved_actor_email),
        ]
        if target_id is not None or target_name is not None:
            pairs.append(
                ("target", f"{target_type or 'unknown'}:{target_id}" if target_id else None)
            )
            pairs.append(("target_name", target_name))
        elif target_type is not None:
            pairs.append(("target_type", target_type))

        for key, value in detail.items():
            pairs.append((key, _REDACTED if _is_sensitive(key) and value is not None else value))

        logger.info("audit %s", _render(pairs))
    except Exception:  # pragma: no cover - an audit failure must never break a request
        logger.warning("audit emit failed for action=%s", action, exc_info=True)
