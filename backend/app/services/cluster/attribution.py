"""What the executing instance stamps onto a run's history row."""

from __future__ import annotations

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
