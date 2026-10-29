"""Audit line for a workflow run that an API entry point started.

Only routers call this. A run started by a schedule, a queue or an event bus executes on
whichever instance claimed it, so its trail lives in ``execution_history`` instead (see
the audit rules in AGENTS.md).
"""

import uuid
from dataclasses import dataclass

from app.db.models import User
from app.services.audit_log import OUTCOME_FAILURE, OUTCOME_SUCCESS, audit

# Statuses where the caller got what it asked for. ``pending`` is a run parked for a human
# and ``queued`` one admitted behind a concurrency limit; neither failed.
_ACCEPTED_STATUSES = frozenset({"success", "pending", "queued"})


@dataclass(frozen=True)
class RunActor:
    """Who started a run, copied out of the ORM row.

    A streamed run is audited after its request ended, when the user row may be detached,
    so the identity is read once while the request is still open.
    """

    id: uuid.UUID | None = None
    email: str | None = None

    @classmethod
    def of(cls, user: User | None) -> "RunActor":
        """Snapshot a user; ``None`` stands for an anonymous or token-authenticated caller."""
        if user is None:
            return cls()
        return cls(id=getattr(user, "id", None), email=getattr(user, "email", None))


def audit_workflow_run(
    *,
    workflow_id: uuid.UUID,
    workflow_name: str,
    status: str,
    execution_time_ms: float | None,
    trigger_source: str,
    execution_id: uuid.UUID | None = None,
    actor: RunActor | None = None,
    test_run: bool = False,
) -> None:
    """Record who ran a workflow, how it was started and how it ended."""
    actor = actor or RunActor()
    audit(
        action="workflow.run",
        outcome=OUTCOME_SUCCESS if status in _ACCEPTED_STATUSES else OUTCOME_FAILURE,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="workflow",
        target_id=workflow_id,
        target_name=workflow_name,
        status=status,
        trigger_source=trigger_source,
        execution_id=execution_id,
        duration_ms=round(execution_time_ms) if execution_time_ms is not None else None,
        test_run=test_run,
    )
