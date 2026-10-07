"""Saving a workflow graph the way the editor does.

A save that changes the graph stores what it replaced as the workflow's next version, so
Edit History can restore it; every save then resyncs websocket triggers and publishes the
platform event. The editor's update endpoint and chat build mode both save through here.
`audit()` stays with the callers in `app/api/`.
"""

import copy
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workflow, WorkflowVersion
from app.services.heym_event_service import (
    EVENT_WORKFLOW_CREATED,
    EVENT_WORKFLOW_UPDATED,
    publish_event,
    workflow_event_payload,
)

PublishEvent = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class WorkflowSnapshot:
    """The versioned fields of a workflow, as they were before a save."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    auth_type: Any
    auth_header_key: str | None
    auth_header_value: str | None
    webhook_body_mode: Any
    cache_ttl_seconds: int | None
    rate_limit_requests: int | None
    rate_limit_window_seconds: int | None

    @classmethod
    def capture(cls, workflow: Workflow) -> "WorkflowSnapshot":
        """Copy the versioned fields before a save changes them."""
        return cls(
            nodes=copy.deepcopy(workflow.nodes or []),
            edges=copy.deepcopy(workflow.edges or []),
            auth_type=workflow.auth_type,
            auth_header_key=workflow.auth_header_key,
            auth_header_value=workflow.auth_header_value,
            webhook_body_mode=workflow.webhook_body_mode,
            cache_ttl_seconds=workflow.cache_ttl_seconds,
            rate_limit_requests=workflow.rate_limit_requests,
            rate_limit_window_seconds=workflow.rate_limit_window_seconds,
        )


async def add_workflow_version(
    db: AsyncSession,
    workflow: Workflow,
    before: WorkflowSnapshot,
    actor_id: uuid.UUID,
) -> int:
    """Store what a save replaced as the workflow's next version and return its number.

    The version carries the workflow's current name and description with the replaced
    graph and settings, as the editor has always stored it.
    """
    result = await db.execute(
        select(func.max(WorkflowVersion.version_number)).where(
            WorkflowVersion.workflow_id == workflow.id
        )
    )
    version_number = (result.scalar() or 0) + 1
    db.add(
        WorkflowVersion(
            workflow_id=workflow.id,
            version_number=version_number,
            name=workflow.name,
            description=workflow.description,
            nodes=before.nodes,
            edges=before.edges,
            auth_type=before.auth_type,
            auth_header_key=before.auth_header_key,
            auth_header_value=before.auth_header_value,
            webhook_body_mode=before.webhook_body_mode,
            cache_ttl_seconds=before.cache_ttl_seconds,
            rate_limit_requests=before.rate_limit_requests,
            rate_limit_window_seconds=before.rate_limit_window_seconds,
            created_by_id=actor_id,
        )
    )
    return version_number


async def announce_workflow_saved(
    workflow: Workflow,
    actor_id: uuid.UUID,
    *,
    created: bool = False,
    publish: PublishEvent = publish_event,
) -> None:
    """Resync websocket triggers and publish the workflow's created or updated event.

    Call it after the save is committed. Dashboard widgets are Workflow rows too, but only
    real workflows produce platform events. Callers pass their own `publish` so tests that
    patch it where they import it keep working.
    """
    from app.services.websocket_trigger_service import websocket_trigger_manager

    websocket_trigger_manager.request_sync()
    if getattr(workflow, "kind", "workflow") != "workflow":
        return
    payload = workflow_event_payload(workflow, actor_user_id=actor_id)
    if created:
        await publish(
            name=EVENT_WORKFLOW_CREATED,
            payload=payload,
            owner_id=workflow.owner_id,
            workflow_id=workflow.id,
            dedupe_key=f"{EVENT_WORKFLOW_CREATED}:{workflow.id}",
        )
        return
    # Key on the saved revision so a retried or duplicated save collapses onto one event
    # instead of waking every subscriber twice.
    await publish(
        name=EVENT_WORKFLOW_UPDATED,
        payload=payload,
        owner_id=workflow.owner_id,
        workflow_id=workflow.id,
        dedupe_key=f"{EVENT_WORKFLOW_UPDATED}:{workflow.id}:{payload['updated_at']}",
    )
