from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.schemas import (
    HITLDecisionRequest,
    HITLDecisionResponse,
    HITLPublicResponse,
)
from app.services.hitl_service import (
    build_hitl_resolved_output,
    ensure_hitl_request_is_actionable,
    ensure_hitl_request_is_viewable,
    get_hitl_request_by_token,
    resume_hitl_request_in_background,
)

router = APIRouter()


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

    ensure_hitl_request_is_actionable(hitl_request)

    if payload.action == "edit" and not (payload.edited_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="edited_text is required for edit action",
        )

    hitl_request.decision = payload.action
    hitl_request.edited_text = (payload.edited_text or "").strip() or None
    hitl_request.refusal_reason = (payload.refusal_reason or "").strip() or None
    hitl_request.status = "resolved"
    hitl_request.resolved_at = datetime.now(timezone.utc)
    hitl_request.resume_error = None
    hitl_request.resolved_output = build_hitl_resolved_output(hitl_request)
    await db.flush()
    await db.commit()

    background_tasks.add_task(resume_hitl_request_in_background, hitl_request.id)
    return HITLDecisionResponse(request_id=hitl_request.id, status=hitl_request.status)
