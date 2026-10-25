"""MCP side of the concurrency limit: the queued tool result and heym_execution_status."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.db.models import ExecutionHistory, WorkflowRunQueue
from app.db.session import async_session_maker
from app.models.schemas import MCPTool, MCPToolInputProperty, MCPToolInputSchema
from app.services import workflow_concurrency

MCP_EXECUTION_STATUS_TOOL_NAME = "heym_execution_status"
NEXT_STEP = (
    f"Call {MCP_EXECUTION_STATUS_TOOL_NAME} with this execution_id every 5-10 seconds "
    "until status is success, error, cancelled or expired."
)


def should_list(workflows: Sequence[Any]) -> bool:
    """Offer the tool only where a run can actually be queued."""
    return any(getattr(w, "concurrency_limit", None) is not None for w in workflows)


def build_execution_status_tool() -> MCPTool:
    return MCPTool(
        name=MCP_EXECUTION_STATUS_TOOL_NAME,
        description=(
            "Get the status of a workflow run that was queued because the workflow reached "
            "its concurrency limit. Returns status (queued, running, success, error, "
            "cancelled, expired), the queue position while queued, and the outputs when done."
        ),
        inputSchema=MCPToolInputSchema(
            type="object",
            properties={
                "execution_id": MCPToolInputProperty(
                    type="string",
                    description="The execution_id returned by the queued tool call.",
                )
            },
            required=["execution_id"],
        ),
    )


def admission_tool_text(admission: workflow_concurrency.Admission) -> tuple[str, bool]:
    """Tool text for a run that did not start: (text, is_error)."""
    if admission.kind == "queue_full":
        return workflow_concurrency.QUEUE_FULL_MESSAGE, True
    payload = {
        "status": "queued",
        "execution_id": str(admission.execution_id),
        "queue": admission.queue.as_dict() if admission.queue else None,
        "next_step": NEXT_STEP,
    }
    return json.dumps(payload, indent=2), False


async def _workflow_of_execution(execution_id: uuid.UUID) -> uuid.UUID | None:
    async with async_session_maker() as db:
        workflow_id = (
            await db.execute(
                select(WorkflowRunQueue.workflow_id).where(
                    WorkflowRunQueue.execution_id == execution_id
                )
            )
        ).scalar_one_or_none()
        if workflow_id is not None:
            return workflow_id
        return (
            await db.execute(
                select(ExecutionHistory.workflow_id).where(ExecutionHistory.id == execution_id)
            )
        ).scalar_one_or_none()


async def run_execution_status_tool(
    workflows: Sequence[Any], arguments: dict[str, Any]
) -> tuple[str, bool]:
    """Status of one run of a workflow this MCP surface exposes: (text, is_error)."""
    not_found = ("Execution not found", True)
    try:
        execution_id = uuid.UUID(str(arguments.get("execution_id", "")))
    except ValueError:
        return "execution_id must be a UUID", True
    workflow_id = await _workflow_of_execution(execution_id)
    if workflow_id is None or workflow_id not in {w.id for w in workflows}:
        return not_found
    body = await workflow_concurrency.build_status_body(workflow_id, execution_id)
    if body is None:
        return not_found
    return json.dumps(body, indent=2, ensure_ascii=False, default=str), False
