import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import HITLRequest, User
from app.db.session import get_db
from app.models.schemas import (
    HITLDecisionRequest,
    HITLDecisionResponse,
    HITLInboxItem,
    HITLInboxLinkResponse,
    HITLInboxResponse,
    HITLPublicResponse,
)
from app.services.hitl_service import (
    build_default_public_base_url,
    build_hitl_resolved_output,
    build_review_url,
    claim_hitl_request_for_decision,
    ensure_hitl_request_is_actionable,
    ensure_hitl_request_is_viewable,
    get_hitl_request_by_token,
    get_owned_hitl_request,
    list_pending_hitl_for_owner,
    refresh_hitl_request_after_lost_claim,
    resume_hitl_request_in_background,
)

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
    return HITLDecisionResponse(request_id=hitl_request.id, status=hitl_request.status)


@router.get("/inbox", response_model=HITLInboxResponse)
async def list_hitl_inbox(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HITLInboxResponse:
    """Pending human reviews for workflows the caller owns.

    The review token stays out of this payload. Open a review through the link route.
    """
    total, rows = await list_pending_hitl_for_owner(db, current_user.id)
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
    """Accept, edit, or refuse a pending review owned by the caller."""
    hitl_request = await get_owned_hitl_request(db, request_id, current_user.id)
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
