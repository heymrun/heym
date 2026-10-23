"""A HITL widget's review filter where it is read and where it is saved.

The filter is stored data that anyone with write access to the widget can set, so it only
narrows what the viewer may already see. Every read re-checks the viewer's review scope;
saves from Settings, AI fine-tune and the canvas refuse a changed filter outside the saver's.
Other writers (imports, clones, chat build) are covered by the read check alone.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DashboardWidget, Workflow
from app.models.dashboard_schemas import HitlWidgetFilterModel, WidgetDataResponse
from app.services.hitl_service import ensure_review_source, filter_in_review_scope
from app.services.hitl_widget_filter import (
    HITL_FILTER_ACCESS_ERROR,
    HITL_FILTER_READ_ONLY_ACCESS_ERROR,
    HitlWidgetFilter,
    ReviewSource,
    filter_from_payload,
    has_hitl_chart,
    hitl_filter_changed,
    hitl_widget_filter,
    with_hitl_widget_filter,
)
from app.services.workflow_save import WorkflowSnapshot, add_workflow_version

HITL_WIDGET_TYPE = "hitl"
AI_FILTER_ERROR = "The model chose a workflow or step with no reviews to show. Try again."


def hitl_filter_model(widget: DashboardWidget, nodes: object) -> HitlWidgetFilterModel | None:
    """The filter a widget response carries: set only on a HITL widget that has one."""
    if widget.chart_type != HITL_WIDGET_TYPE:
        return None
    value = hitl_widget_filter(nodes)
    if value is None:
        return None
    return HitlWidgetFilterModel(workflow_id=value.workflow_id, node_id=value.node_id)


async def hitl_filters_for_widgets(
    db: AsyncSession, widgets: Sequence[DashboardWidget]
) -> dict[uuid.UUID, HitlWidgetFilterModel]:
    """The filter of each HITL widget among ``widgets``, by widget id, in one query."""
    widgets_by_workflow: dict[uuid.UUID, list[DashboardWidget]] = {}
    for widget in widgets:
        if widget.chart_type == HITL_WIDGET_TYPE:
            widgets_by_workflow.setdefault(widget.workflow_id, []).append(widget)
    if not widgets_by_workflow:
        return {}
    result = await db.execute(
        select(Workflow.id, Workflow.nodes).where(Workflow.id.in_(list(widgets_by_workflow)))
    )
    filters: dict[uuid.UUID, HitlWidgetFilterModel] = {}
    for row in result.all():
        for widget in widgets_by_workflow.get(row.id, []):
            model = hitl_filter_model(widget, row.nodes)
            if model is not None:
                filters[widget.id] = model
    return filters


async def check_hitl_filter_access(
    db: AsyncSession, response: WidgetDataResponse, viewer_id: uuid.UUID, *, read_only: bool
) -> WidgetDataResponse:
    """Replace a filtered HITL chart with an error when the viewer may not see its workflow.

    A deleted workflow and someone else's give the same message, which never names it.
    """
    value = filter_from_payload(response.payload)
    if value is None or await filter_in_review_scope(db, viewer_id, value):
        return response
    error = HITL_FILTER_READ_ONLY_ACCESS_ERROR if read_only else HITL_FILTER_ACCESS_ERROR
    return response.model_copy(update={"payload": None, "error": error})


async def ensure_saved_filter_allowed(
    db: AsyncSession,
    actor_id: uuid.UUID,
    old_nodes: object,
    new_nodes: object,
    *,
    detail: str | None = None,
) -> None:
    """Refuse a save that points a HITL widget at reviews outside the saver's scope.

    An unchanged filter is not checked again, so an editor who cannot see the chosen
    workflow can still save the rest of the widget.
    """
    if not hitl_filter_changed(old_nodes, new_nodes):
        return
    value = hitl_widget_filter(new_nodes)
    if value is None:
        return
    try:
        await ensure_review_source(db, actor_id, value)
    except HTTPException as exc:
        if detail is None:
            raise
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


async def apply_hitl_filter(
    db: AsyncSession,
    widget: DashboardWidget,
    value: HitlWidgetFilterModel | None,
    actor_id: uuid.UUID,
) -> None:
    """Point a HITL widget at one workflow or step, or back at every review.

    The change is a workflow edit like any other: the graph it replaces goes to Edit History.
    """
    if widget.chart_type != HITL_WIDGET_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only a HITL widget shows reviews from a workflow",
        )
    workflow = (
        await db.execute(select(Workflow).where(Workflow.id == widget.workflow_id))
    ).scalar_one_or_none()
    if workflow is None or not has_hitl_chart(workflow.nodes):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Widget workflow not found"
        )
    new_filter = (
        None
        if value is None
        else HitlWidgetFilter(value.workflow_id, (value.node_id or "").strip() or None)
    )
    if new_filter == hitl_widget_filter(workflow.nodes):
        return
    if new_filter is not None:
        await ensure_review_source(db, actor_id, new_filter)
    await add_workflow_version(db, workflow, WorkflowSnapshot.capture(workflow), actor_id)
    workflow.nodes = with_hitl_widget_filter(list(workflow.nodes or []), new_filter)
    # Only the workflow changed; the widget's updated_at is what makes its card reload.
    widget.updated_at = datetime.now(timezone.utc)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def hitl_sources_context(sources: Sequence[ReviewSource]) -> str:
    """What a HITL widget's fine-tune is told about the workflows it can show reviews from."""
    if not sources:
        return (
            "This HITL widget can only show every review: the user has no workflow with a "
            "step that waits for a person. Leave hitlWorkflowId and hitlNodeId out."
        )
    lines = [
        "Review sources this HITL widget can show. To show one workflow's reviews, set "
        "hitlWorkflowId on the hitl chartOutput to its id; to show one step of it, also set "
        "hitlNodeId to that step's id. Leave both out to show every review. Use only these ids:"
    ]
    for source in sources:
        steps = "; ".join(
            f"{_one_line(step.label)} (hitlNodeId {step.node_id}, "
            f"{'Slack' if step.kind == 'slack' else 'agent'})"
            for step in source.steps
        )
        lines.append(
            f"- {_one_line(source.workflow_name)} (hitlWorkflowId {source.workflow_id}): {steps}"
        )
    return "\n".join(lines)
