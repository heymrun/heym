import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import DashboardWidget, HITLRequest, User, Workflow
from app.db.session import get_db
from app.models.schemas import (
    HITLDashboardCountsResponse,
    HITLDecisionRequest,
    HITLDecisionResponse,
    HITLInboxItem,
    HITLInboxLinkResponse,
    HITLInboxResponse,
    HITLPublicResponse,
    HITLReviewSource,
    HITLReviewSourcesResponse,
    HITLReviewSourceStep,
)
from app.services.dashboard_access import reachable_dashboard_ids
from app.services.hitl_service import (
    build_default_public_base_url,
    build_hitl_resolved_output,
    build_review_url,
    claim_hitl_request_for_decision,
    count_pending_by_step,
    count_pending_in_workflows,
    ensure_hitl_request_is_actionable,
    ensure_hitl_request_is_viewable,
    filter_reachable,
    get_decidable_hitl_request,
    get_hitl_request_by_token,
    get_owned_hitl_request,
    list_pending_hitl_for_owner,
    list_review_sources,
    refresh_hitl_request_after_lost_claim,
    resume_hitl_request_in_background,
)
from app.services.hitl_widget_filter import (
    HITL_FILTER_ACCESS_ERROR,
    HitlWidgetFilter,
    hitl_widget_filter,
    pending_for_widgets,
)
from app.services.slack_interactions import sync_message_after_heym_decision

router = APIRouter()


async def _complete_hitl_decision(
    hitl_request: HITLRequest,
    payload: HITLDecisionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> HITLDecisionResponse:
    """Claim one pending review and schedule its resume. Shared by the public link and the inbox."""
    ensure_hitl_request_is_actionable(hitl_request)

    if payload.action == "edit" and not (payload.edited_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="edited_text is required for edit action",
        )

    edited_text = (payload.edited_text or "").strip() or None
    refusal_reason = (payload.refusal_reason or "").strip() or None

    claimed = await claim_hitl_request_for_decision(
        db,
        hitl_request,
        decision=payload.action,
        edited_text=edited_text,
        refusal_reason=refusal_reason,
    )
    if not claimed:
        raise await refresh_hitl_request_after_lost_claim(db, hitl_request)

    hitl_request.decision = payload.action
    hitl_request.edited_text = edited_text
    hitl_request.refusal_reason = refusal_reason
    hitl_request.status = "resolved"
    hitl_request.resolved_at = datetime.now(timezone.utc)
    hitl_request.resume_error = None
    hitl_request.resolved_output = build_hitl_resolved_output(hitl_request)
    await db.commit()

    background_tasks.add_task(resume_hitl_request_in_background, hitl_request.id)
    if isinstance((hitl_request.original_agent_output or {}).get("_slack"), dict):
        background_tasks.add_task(sync_message_after_heym_decision, hitl_request.id)
    return HITLDecisionResponse(request_id=hitl_request.id, status=hitl_request.status)


MAX_COUNTED_DASHBOARDS = 100


@router.get("/inbox", response_model=HITLInboxResponse)
async def list_hitl_inbox(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workflow_id: Annotated[
        uuid.UUID | None, Query(description="Only reviews from this workflow.")
    ] = None,
    node_id: Annotated[
        str | None, Query(max_length=64, description="Only reviews from this step of it.")
    ] = None,
) -> HITLInboxResponse:
    """Pending human reviews: the caller's own queue, or one workflow's.

    Without ``workflow_id`` the queue is the workflows the caller owns. With it, it is that
    workflow's reviews, for anyone who can open the workflow. A workflow they cannot open is a
    403, not an empty list, so a HITL widget pointed at it says so. The review token stays out
    of this payload; the owner opens a review through the link route.
    """
    node_id = (node_id or "").strip() or None
    if node_id is not None and workflow_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="node_id needs workflow_id",
        )
    if workflow_id is not None and not await filter_reachable(
        db, current_user.id, HitlWidgetFilter(workflow_id=workflow_id, node_id=node_id)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=HITL_FILTER_ACCESS_ERROR)
    total, rows = await list_pending_hitl_for_owner(
        db, current_user.id, workflow_id=workflow_id, node_id=node_id
    )
    return HITLInboxResponse(
        pending_total=total,
        items=[
            HITLInboxItem(
                id=row.id,
                workflow_id=row.workflow_id,
                execution_history_id=row.execution_history_id,
                workflow_name=row.workflow_name,
                agent_label=row.agent_label,
                summary=row.summary,
                text=row.original_draft_text,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.get("/sources", response_model=HITLReviewSourcesResponse)
async def list_hitl_review_sources(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HITLReviewSourcesResponse:
    """Workflows the caller can open with a step that waits for a person, for a HITL widget.

    Agents with human review and Slack approvals, buttons and forms, in workflows the caller
    owns or that are shared with them or their team.
    """
    sources = await list_review_sources(db, current_user.id)
    return HITLReviewSourcesResponse(
        sources=[
            HITLReviewSource(
                workflow_id=source.workflow_id,
                workflow_name=source.workflow_name,
                steps=[
                    HITLReviewSourceStep(node_id=step.node_id, label=step.label, kind=step.kind)
                    for step in source.steps
                ],
            )
            for source in sources
        ]
    )


@router.get("/inbox/dashboard-counts", response_model=HITLDashboardCountsResponse)
async def count_hitl_dashboard_reviews(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    dashboard_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> HITLDashboardCountsResponse:
    """The caller's pending reviews each dashboard's HITL widgets show, for page badges.

    Dashboards the caller cannot open, or without a HITL widget, are left out. An unfiltered
    widget counts the caller's own queue; a filtered one counts its workflow's reviews when
    the caller can open that workflow, and nothing otherwise.
    """
    wanted = set(dashboard_id or [])
    if len(wanted) > MAX_COUNTED_DASHBOARDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"At most {MAX_COUNTED_DASHBOARDS} dashboards per request",
        )
    reachable = await reachable_dashboard_ids(db, wanted, current_user.id)
    if not reachable:
        return HITLDashboardCountsResponse(counts={})
    rows = await db.execute(
        select(DashboardWidget.dashboard_id, Workflow.nodes)
        .join(Workflow, Workflow.id == DashboardWidget.workflow_id)
        .where(DashboardWidget.dashboard_id.in_(reachable), DashboardWidget.chart_type == "hitl")
    )
    filters_by_dashboard: dict[uuid.UUID, list[HitlWidgetFilter | None]] = {}
    for row in rows.all():
        filters_by_dashboard.setdefault(row.dashboard_id, []).append(hitl_widget_filter(row.nodes))
    if not filters_by_dashboard:
        return HITLDashboardCountsResponse(counts={})
    chosen_ids = {
        value.workflow_id
        for filters in filters_by_dashboard.values()
        for value in filters
        if value is not None
    }
    own = await count_pending_by_step(db, current_user.id)
    chosen = await count_pending_in_workflows(db, current_user.id, chosen_ids)
    return HITLDashboardCountsResponse(
        counts={
            str(dashboard): pending_for_widgets(own, chosen, filters)
            for dashboard, filters in filters_by_dashboard.items()
        }
    )


@router.get("/inbox/{request_id}/link", response_model=HITLInboxLinkResponse)
async def get_hitl_inbox_link(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HITLInboxLinkResponse:
    """Return the public review URL for a review the caller owns."""
    hitl_request = await get_owned_hitl_request(db, request_id, current_user.id)
    ensure_hitl_request_is_viewable(hitl_request)
    url = build_review_url(build_default_public_base_url(), hitl_request.public_token)
    return HITLInboxLinkResponse(url=url)


@router.post(
    "/inbox/{request_id}/decision",
    response_model=HITLDecisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_owned_hitl_decision(
    request_id: uuid.UUID,
    payload: HITLDecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HITLDecisionResponse:
    """Accept, edit, or refuse a pending review of a workflow the caller can open.

    Deciding resumes the run, which anyone who can open the workflow may run.
    """
    hitl_request = await get_decidable_hitl_request(db, request_id, current_user.id)
    return await _complete_hitl_decision(hitl_request, payload, background_tasks, db)


@router.get("/{token}", response_model=HITLPublicResponse)
async def get_hitl_request(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> HITLPublicResponse:
    hitl_request = await get_hitl_request_by_token(db, token)
    if hitl_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found"
        )
    ensure_hitl_request_is_viewable(hitl_request)

    return HITLPublicResponse(
        request_id=hitl_request.id,
        workflow_name=hitl_request.workflow_name,
        agent_label=hitl_request.agent_label,
        summary=hitl_request.summary,
        original_draft_text=hitl_request.original_draft_text,
        status=hitl_request.status,
        decision=hitl_request.decision,
        edited_text=hitl_request.edited_text,
        refusal_reason=hitl_request.refusal_reason,
        resolved_output=hitl_request.resolved_output or {},
        expires_at=hitl_request.expires_at,
        resolved_at=hitl_request.resolved_at,
    )


@router.post(
    "/{token}/decision",
    response_model=HITLDecisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_hitl_decision(
    token: str,
    payload: HITLDecisionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> HITLDecisionResponse:
    hitl_request = await get_hitl_request_by_token(db, token)
    if hitl_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found"
        )

    return await _complete_hitl_decision(hitl_request, payload, background_tasks, db)
