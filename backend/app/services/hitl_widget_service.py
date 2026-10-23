"""A HITL widget's review filter where it is read and where it is saved.

The filter is stored data that anyone with write access to the widget can set, so it never
stands in for access. Every read re-checks that the viewer can open the chosen workflow: a
viewer who cannot does not see the widget, and the dashboard's owner sees why. Saves from
Settings, AI create and fine-tune, and the canvas refuse a changed filter on a workflow the
saver cannot open. Other writers (imports, clones, chat build) are covered by the read check.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DashboardWidget, Workflow
from app.models.dashboard_schemas import HitlWidgetFilterModel, WidgetDataResponse
from app.services.hitl_service import ensure_review_source, reachable_review_workflows
from app.services.hitl_widget_filter import (
    HITL_FILTER_ACCESS_ERROR,
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
# The widget a viewer may not see answers as a widget that does not exist.
HIDDEN_WIDGET_DETAIL = "Widget not found"
# The AI is told about at most this many workflows with review steps.
MAX_SOURCES_IN_PROMPT = 40


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


async def hidden_hitl_widgets(
    db: AsyncSession,
    filters: dict[uuid.UUID, HitlWidgetFilterModel],
    viewer_id: uuid.UUID,
    dashboard_owner_id: uuid.UUID,
) -> set[uuid.UUID]:
    """The filtered HITL widgets the viewer may not see, by widget id.

    A widget filtered on a workflow the viewer cannot open is left off their dashboard. The
    dashboard's owner keeps it, with an access error, so they can point it elsewhere.
    """
    if viewer_id == dashboard_owner_id or not filters:
        return set()
    reachable = await reachable_review_workflows(
        db, viewer_id, {value.workflow_id for value in filters.values()}
    )
    return {widget_id for widget_id, value in filters.items() if value.workflow_id not in reachable}


async def check_hitl_filter_access(
    db: AsyncSession,
    response: WidgetDataResponse,
    viewer_id: uuid.UUID,
    *,
    dashboard_owner: bool,
) -> WidgetDataResponse:
    """A filtered HITL chart for a viewer who can open its workflow; otherwise none.

    The dashboard's owner gets an access error in place of the reviews; anyone else gets the
    404 of a widget that does not exist. Neither names the workflow, so a deleted workflow and
    someone else's look the same.
    """
    value = filter_from_payload(response.payload)
    if value is None or value.workflow_id in await reachable_review_workflows(
        db, viewer_id, [value.workflow_id]
    ):
        return response
    if not dashboard_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=HIDDEN_WIDGET_DETAIL)
    return response.model_copy(update={"payload": None, "error": HITL_FILTER_ACCESS_ERROR})


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
    """What the AI is told about the workflows a HITL widget can show reviews from."""
    if not sources:
        return (
            "A HITL widget can only show every review: the user has no workflow with a "
            "step that waits for a person. Leave hitlWorkflowId and hitlNodeId out."
        )
    lines = [
        "Review sources a HITL widget can show. When the request names one of these workflows "
        "(or one of its steps), set hitlWorkflowId on the hitl chartOutput to its id, and "
        "hitlNodeId to the step's id for one step. Otherwise leave both out to show every "
        "review. Use only these ids:"
    ]
    for source in sources[:MAX_SOURCES_IN_PROMPT]:
        steps = "; ".join(
            f"{_one_line(step.label)} (hitlNodeId {step.node_id}, "
            f"{'Slack' if step.kind == 'slack' else 'agent'})"
            for step in source.steps
        )
        lines.append(
            f"- {_one_line(source.workflow_name)} (hitlWorkflowId {source.workflow_id}): {steps}"
        )
    return "\n".join(lines)
