"""Admin-only cluster configuration, gated by HEYM_ADMIN_EMAILS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_instance_admin
from app.config import settings
from app.db.models import ClusterDispatchState, ClusterInstance, User, WorkflowRunQueue
from app.db.session import get_db
from app.models.schemas import (
    ClusterInstanceResponse,
    ClusterInstanceUpdate,
    ClusterSettingsResponse,
    ClusterSettingsUpdate,
)
from app.services.cluster import registry

router = APIRouter()


def validate_weight_map(weights: dict[str, tuple[bool, int]]) -> None:
    """Reject a split nothing could run on.

    Weights are shares of whichever instances can currently take work, not
    percentages of 100: the scheduler divides by the pool's own total. Demanding
    a total of 100 would fail the moment an instance is disabled or goes
    offline, even though the cluster keeps working - so only genuinely unusable
    input is rejected here.
    """
    if any(weight < 0 for _enabled, weight in weights.values()):
        raise ValueError("Weights cannot be negative.")
    if not any(enabled for enabled, _weight in weights.values()):
        raise ValueError("At least one instance must be enabled.")
    if sum(weight for enabled, weight in weights.values() if enabled) <= 0:
        raise ValueError("At least one enabled instance needs a weight above zero.")


def ensure_main_enabled(role: str, enabled: bool) -> None:
    """The main instance cannot be taken out of rotation.

    Disabling it would drop it from the ANYWHERE pool while MAIN_ONLY work -
    files, plugins, coding agents, email - still routes there and still runs
    in-process. The toggle would stop describing what actually happens.
    """
    if role == "main" and not enabled:
        raise ValueError("The main instance cannot be disabled.")


def placement_ratio(*, main_only: int, anywhere: int) -> dict[str, int]:
    """How much of the recent workload could not leave the main instance."""
    total = main_only + anywhere
    if total == 0:
        return {"mainOnlyPercent": 0, "anywherePercent": 0}
    main_percent = round(main_only * 100 / total)
    return {"mainOnlyPercent": main_percent, "anywherePercent": 100 - main_percent}


async def _read_cluster(db: AsyncSession) -> ClusterSettingsResponse:
    instances = await registry.list_instances()
    now = datetime.now(timezone.utc)
    main = registry.find_main(instances)
    connected = await registry.connected_instance_ids()

    since = now - timedelta(hours=24)
    counts = dict(
        (
            await db.execute(
                select(WorkflowRunQueue.placement, func.count())
                .where(WorkflowRunQueue.enqueued_at >= since)
                .group_by(WorkflowRunQueue.placement)
            )
        ).all()
    )

    state = (
        await db.execute(select(ClusterDispatchState).where(ClusterDispatchState.id == "singleton"))
    ).scalar_one_or_none()

    return ClusterSettingsResponse(
        cluster_enabled=settings.cluster_enabled,
        automatic_weighting=state.automatic_weighting if state else True,
        instances=[
            ClusterInstanceResponse(
                id=i.id,
                name=i.name,
                role=i.role,
                enabled=i.enabled,
                weight=i.weight,
                weight_configured=i.weight_configured,
                version=i.version,
                docker_ok=i.docker_ok,
                db_latency_ms=i.db_latency_ms,
                live=registry.is_live_now(i, now=now, connected_ids=connected),
                compatible=main is not None and registry.is_compatible_with(i, main),
                heartbeat_at=i.heartbeat_at,
            )
            # Main first, then workers by id, so the table order is stable.
            for i in sorted(instances, key=lambda i: (i.role != "main", i.id))
        ],
        placement_ratio=placement_ratio(
            main_only=counts.get("main_only", 0), anywhere=counts.get("anywhere", 0)
        ),
    )


@router.get("", response_model=ClusterSettingsResponse)
async def read_cluster(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ClusterSettingsResponse:
    require_instance_admin(current_user)
    return await _read_cluster(db)


@router.put("/instances", response_model=ClusterSettingsResponse)
async def update_instances(
    updates: dict[str, ClusterInstanceUpdate],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClusterSettingsResponse:
    require_instance_admin(current_user)
    try:
        validate_weight_map({k: (v.enabled, v.weight) for k, v in updates.items()})
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    for instance_id, update in updates.items():
        row = (
            await db.execute(select(ClusterInstance).where(ClusterInstance.id == instance_id))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown instance: {instance_id}"
            )
        try:
            ensure_main_enabled(row.role, update.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        row.name = update.name.strip() or row.id
        row.enabled = update.enabled
        row.weight = update.weight
        # An operator's number is deliberate, so this instance is never seeded.
        row.weight_configured = True
    await db.commit()
    return await _read_cluster(db)


@router.put("", response_model=ClusterSettingsResponse)
async def update_cluster(
    update: ClusterSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClusterSettingsResponse:
    """Toggle automatic weighting. Instances are updated through /instances."""
    require_instance_admin(current_user)
    if update.automatic_weighting is not None:
        state = (
            await db.execute(
                select(ClusterDispatchState).where(ClusterDispatchState.id == "singleton")
            )
        ).scalar_one_or_none()
        if state is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cluster state row is missing."
            )
        state.automatic_weighting = update.automatic_weighting
        await db.commit()
    return await _read_cluster(db)


@router.delete("/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(
    instance_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    require_instance_admin(current_user)
    row = (
        await db.execute(select(ClusterInstance).where(ClusterInstance.id == instance_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown instance")
    if row.role == "main":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The main instance cannot be removed."
        )
    await db.delete(row)
    await db.commit()
