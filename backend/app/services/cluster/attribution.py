"""What the executing instance stamps onto a run's history row."""

from __future__ import annotations

import uuid

from app.config import settings
from app.services.cluster import identity


def attribution_fields() -> dict[str, str | None]:
    """Instance id and a snapshot of its label, or nulls outside a cluster.

    The name is snapshotted rather than joined so history keeps its meaning
    after an instance is renamed or removed from the cluster.
    """
    if not settings.cluster_enabled:
        return {"executed_by_instance_id": None, "executed_by_instance_name": None}
    return {
        "executed_by_instance_id": identity.instance_id(),
        "executed_by_instance_name": identity.instance_name(),
    }


STARTED_BY_USER_OPTION = "started_by_user_id"


def started_by_user_options(user_id: uuid.UUID | None) -> dict[str, str]:
    """The run option that carries the starting user across the queue; empty without one."""
    return {STARTED_BY_USER_OPTION: str(user_id)} if user_id is not None else {}


def started_by_user(options: dict | None) -> uuid.UUID | None:
    """The user a queued run was started by, from its run options."""
    value = (options or {}).get(STARTED_BY_USER_OPTION)
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
