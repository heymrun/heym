"""Generic HTTP webhook trigger endpoint."""

import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.api.workflows import execute_workflow_request
from app.db.models import User, Workflow
from app.db.session import get_db

router = APIRouter()


async def _find_workflow_by_node_id(db: AsyncSession, node_id: str) -> Workflow | None:
    """Use JSONB containment to find the workflow containing this node_id."""
    result = await db.execute(
        select(Workflow).where(
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps([{"id": node_id}])
            )
        )
    )
    return result.scalar_one_or_none()


def _find_webhook_trigger_node(workflow: Workflow, node_id: str) -> dict | None:
    """Return the matching webhookTrigger node, if it exists in this workflow."""
    for node in workflow.nodes or []:
        if node.get("id") != node_id:
            continue
        if node.get("type") != "webhookTrigger":
            return None
        if node.get("data", {}).get("active", True) is False:
            return None
        return node
    return None


@router.api_route("/{node_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def webhook_trigger(
    node_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Receive generic HTTP webhook requests and execute the owning workflow."""
    workflow = await _find_workflow_by_node_id(db, node_id)
    if workflow is None or _find_webhook_trigger_node(workflow, node_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No webhook trigger found for this URL",
        )

    return await execute_workflow_request(
        workflow_id=uuid.UUID(str(workflow.id)),
        request=request,
        background_tasks=background_tasks,
        current_user=current_user,
        db=db,
        default_trigger_source="webhook",
    )
