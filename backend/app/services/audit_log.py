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
from app.services.audit_format import (
    OUTCOME_DENIED,
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    format_audit_line,
)

__all__ = ["OUTCOME_DENIED", "OUTCOME_FAILURE", "OUTCOME_SUCCESS", "audit"]

logger = logging.getLogger("winston.audit")


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

        line = format_audit_line(
            action=action,
            outcome=outcome,
            actor_id=resolved_actor_id,
            actor_email=resolved_actor_email,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            **detail,
        )
        logger.info("%s", line)
    except Exception:  # pragma: no cover - an audit failure must never break a request
        logger.warning("audit emit failed for action=%s", action, exc_info=True)
