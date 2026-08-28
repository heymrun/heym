"""Give a newly joined instance a share of the load, once.

Without this, a worker joins at weight 0, is filtered out of the candidate pool,
and sits Live and Enabled doing nothing until an operator notices. With it, the
leader carves a share on its next pass and the machine starts working.

It runs once per instance and only while automatic weighting is on: an operator
who sets a worker to 0 on purpose is never overruled, and neither is a
deliberate split - existing weights keep their ratios to each other.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import ClusterDispatchState, ClusterInstance
from app.db.session import async_session_maker
from app.services.cluster import registry
from app.services.cluster.weights import seed_weights

logger = logging.getLogger("cluster")


async def read_automatic_weighting() -> bool:
    async with async_session_maker() as db:
        value = (
            await db.execute(
                select(ClusterDispatchState.automatic_weighting).where(
                    ClusterDispatchState.id == "singleton"
                )
            )
        ).scalar_one_or_none()
    return bool(value) if value is not None else True


def seedable_pool(
    instances: list[registry.InstanceView], *, main: registry.InstanceView | None, now: datetime
) -> dict[str, tuple[bool, int]]:
    """The instances a seeding pass may redistribute across.

    Offline and incompatible instances are excluded: handing a share to a
    machine that cannot take work would strand it. Disabled ones are excluded
    too - that is the operator saying "not this one".
    """
    if main is None:
        return {}
    return {
        i.id: (i.weight_configured, i.weight)
        for i in instances
        if i.enabled and registry.is_live(i, now=now) and registry.is_compatible_with(i, main)
    }


async def apply_automatic_weighting() -> dict[str, int] | None:
    """Seed any never-configured instance. Returns the new weights, or None."""
    if not await read_automatic_weighting():
        return None

    instances = await registry.list_instances()
    now = datetime.now(timezone.utc)
    pool = seedable_pool(instances, main=registry.find_main(instances), now=now)
    seeded = seed_weights(pool)
    if seeded is None:
        return None

    async with async_session_maker() as db:
        for instance_id, weight in seeded.items():
            row = (
                await db.execute(select(ClusterInstance).where(ClusterInstance.id == instance_id))
            ).scalar_one_or_none()
            if row is None:
                continue
            row.weight = weight
            # Marked here as well as on an operator save, so a machine is only
            # ever seeded once however it got its number.
            row.weight_configured = True
        await db.commit()

    logger.info("Automatic weighting seeded new instances: %s", seeded)
    return seeded
