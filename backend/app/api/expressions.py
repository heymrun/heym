"""Expression evaluation API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.workflows import get_credentials_context, get_workflow_for_user
from app.db.models import User, Workflow
from app.db.session import get_db
from app.services.expression_evaluator import (
    EXPRESSION_MAX_LENGTH,
    ExpressionEvaluateResponse,
    ExpressionEvaluatorService,
    build_eval_context,
    build_vars_context,
    get_selected_loop_total,
)
from app.services.global_variables_service import get_global_variables_context

router = APIRouter()


class NodeResultItem(BaseModel):
    """A node result supplied by the frontend canvas after a test run."""

    node_id: str
    label: str
    output: Any


class ExpressionEvaluateRequest(BaseModel):
    """Request payload for the unified expression evaluator endpoint."""

    expression: str = Field(..., max_length=EXPRESSION_MAX_LENGTH)
    workflow_id: UUID
    current_node_id: str
    field_name: str | None = None
    input_body: Any = None
    selected_loop_iteration_index: int | None = None
    node_results: list[NodeResultItem] = Field(default_factory=list)


async def get_workflow_by_id(
    workflow_id: UUID,
    db: AsyncSession,
    user: User,
) -> Workflow | None:
    """Load a workflow only when the caller has access to it."""
    return await get_workflow_for_user(db, workflow_id, user.id)


@router.post(
    "/evaluate",
    response_model=ExpressionEvaluateResponse,
    status_code=status.HTTP_200_OK,
)
async def evaluate_expression(
    request: ExpressionEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExpressionEvaluateResponse:
    """Evaluate an expression or template using pinned data and last-run node outputs."""
    workflow = await get_workflow_by_id(request.workflow_id, db, current_user)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    workflow_nodes = list(workflow.nodes or [])
    workflow_edges = list(workflow.edges or [])
    canvas_results = [
        {
            "node_id": item.node_id,
            "label": item.label,
            "output": item.output,
        }
        for item in request.node_results
    ]
    context = build_eval_context(
        workflow_nodes,
        canvas_results,
        workflow_edges=workflow_edges,
        current_node_id=request.current_node_id,
        initial_inputs=request.input_body,
        selected_loop_iteration_index=request.selected_loop_iteration_index,
    )
    vars_context = build_vars_context(
        workflow_nodes,
        canvas_results,
        workflow_edges=workflow_edges,
        current_node_id=request.current_node_id,
    )

    credentials_owner_id = current_user.id if current_user else workflow.owner_id
    credentials_context = await get_credentials_context(db, credentials_owner_id)
    global_variables_context = await get_global_variables_context(db, credentials_owner_id)

    service = ExpressionEvaluatorService(
        workflow_nodes=workflow_nodes,
        workflow_edges=workflow_edges,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        vars_context=vars_context,
    )
    response = service.evaluate(
        request.expression,
        context,
        current_node_id=request.current_node_id,
    )
    response.selected_loop_total = get_selected_loop_total(
        workflow_nodes,
        workflow_edges,
        request.current_node_id,
        context,
        service,
    )
    return response
