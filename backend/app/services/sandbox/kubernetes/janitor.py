"""Deletes sandbox pods nobody will delete: finished ones, and those of dead instances.

Every run and the bridge delete their own pod on every exit path; this covers a
backend that died mid-run. Running pods also end at ``activeDeadlineSeconds``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.pod import LABEL_INSTANCE, LABEL_MANAGED_BY, MANAGED_BY

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 600
FINISHED_GRACE_SECONDS = 600


def _created(pod: dict[str, Any]) -> datetime | None:
    raw = (pod.get("metadata") or {}).get("creationTimestamp")
    try:
        return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def sweep(client: KubeClient, *, in_cluster: bool, now: datetime) -> list[str]:
    """Delete finished pods past the grace period and pods whose instance is gone."""
    removed: list[str] = []
    instance_alive: dict[str, bool] = {}
    for pod in client.list_pods(f"{LABEL_MANAGED_BY}={MANAGED_BY}"):
        metadata = pod.get("metadata") or {}
        name = str(metadata.get("name") or "")
        created = _created(pod)
        phase = (pod.get("status") or {}).get("phase")
        finished = (
            phase in ("Succeeded", "Failed")
            and created is not None
            and (now - created).total_seconds() > FINISHED_GRACE_SECONDS
        )
        orphan = False
        instance = (metadata.get("labels") or {}).get(LABEL_INSTANCE)
        if in_cluster and instance and not finished:
            if instance not in instance_alive:
                owner = client.get_pod(instance, namespace=client.config.own_namespace)
                instance_alive[instance] = owner is not None
            orphan = not instance_alive[instance]
        if name and (finished or orphan):
            client.delete_pod(name)
            removed.append(name)
    return removed


def _kubernetes_backend():  # noqa: ANN202
    from app.services.sandbox.manager import get_sandbox_manager

    manager = get_sandbox_manager()
    if manager.backend_name != "kubernetes" or not manager.available():
        return None
    return manager.backend


async def run_janitor() -> None:
    """Sweep every ten minutes while the Kubernetes backend is in use."""
    backend = await asyncio.to_thread(_kubernetes_backend)
    if backend is None:
        return
    while True:
        try:
            removed = await asyncio.to_thread(
                sweep,
                backend.client,
                in_cluster=backend.config.in_cluster,
                now=datetime.now(timezone.utc),
            )
            if removed:
                logger.info(
                    "Removed %d leftover sandbox pods: %s", len(removed), ", ".join(removed)
                )
        except (KubeApiError, httpx.HTTPError, OSError) as exc:
            logger.warning("Sandbox pod sweep failed: %s", exc)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
