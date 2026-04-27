import asyncio
import copy
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import ExecutionHistory, HITLRequest, Workflow
from app.db.session import async_session_maker
from app.services.workflow_executor import (
    ExecutionResult,
    execute_hitl_notification_branch,
    resume_workflow_execution,
)

HITL_TTL_HOURS = 168


def build_public_base_url(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    if settings.frontend_url:
        return settings.frontend_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def build_review_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/review/{token}"


def ensure_hitl_request_is_viewable(hitl_request: HITLRequest) -> None:
    now = datetime.now(timezone.utc)
    if hitl_request.status == "expired" or hitl_request.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Review link has expired")
    if hitl_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This review link has already been completed.",
        )


def build_hitl_share_text(summary: str, review_url: str) -> str:
    cleaned_summary = summary.strip()
    if cleaned_summary:
        return f"{cleaned_summary}\nReview link: {review_url}"
    return f"Human review required.\nReview link: {review_url}"


def build_hitl_share_markdown(summary: str, review_url: str) -> str:
    cleaned_summary = summary.strip()
    if cleaned_summary:
        return f"{cleaned_summary}\n\n[Open review page]({review_url})"
    return f"Human review required.\n\n[Open review page]({review_url})"


def _build_hitl_history_entry(
    *,
    decision: str,
    summary: str,
    original_draft: str,
    review_text: str,
    request_id: uuid.UUID,
    edited_text: str | None = None,
    refusal_reason: str | None = None,
) -> dict:
    entry = {
        "decision": decision,
        "summary": summary,
        "originalDraft": original_draft,
        "reviewText": review_text,
        "requestId": str(request_id),
    }
    if edited_text is not None:
        entry["editedText"] = edited_text
    if refusal_reason is not None:
        entry["refusalReason"] = refusal_reason
    return entry


def build_hitl_resolved_output(hitl_request: HITLRequest) -> dict:
    output = copy.deepcopy(hitl_request.original_agent_output or {})
    for key in (
        "decision",
        "summary",
        "originalDraft",
        "reviewText",
        "requestId",
        "editedText",
        "refusalReason",
        "approvedMarkdown",
    ):
        output.pop(key, None)
    decision_map = {
        "accept": "accepted",
        "edit": "edited",
        "refuse": "refused",
    }
    resolved_decision = decision_map.get(hitl_request.decision or "", "accepted")
    review_text = hitl_request.original_draft_text
    if hitl_request.decision == "edit":
        output["text"] = hitl_request.edited_text or ""
        review_text = hitl_request.edited_text or ""
    elif hitl_request.decision == "refuse":
        output["text"] = ""
        review_text = hitl_request.refusal_reason or hitl_request.original_draft_text
    else:
        output["text"] = hitl_request.original_draft_text

    output["decision"] = resolved_decision
    output["summary"] = hitl_request.summary
    output["originalDraft"] = hitl_request.original_draft_text
    output["reviewText"] = review_text
    output["requestId"] = str(hitl_request.id)
    if hitl_request.decision == "edit":
        output["editedText"] = hitl_request.edited_text
    if hitl_request.decision == "refuse":
        output["refusalReason"] = hitl_request.refusal_reason

    raw_history = output.get("hitlHistory")
    hitl_history = (
        [copy.deepcopy(entry) for entry in raw_history if isinstance(entry, dict)]
        if isinstance(raw_history, list)
        else []
    )
    current_entry = _build_hitl_history_entry(
        decision=resolved_decision,
        summary=hitl_request.summary,
        original_draft=hitl_request.original_draft_text,
        review_text=review_text,
        request_id=hitl_request.id,
        edited_text=hitl_request.edited_text if hitl_request.decision == "edit" else None,
        refusal_reason=hitl_request.refusal_reason if hitl_request.decision == "refuse" else None,
    )
    if not any(
        str(entry.get("requestId") or "").strip() == str(hitl_request.id) for entry in hitl_history
    ):
        hitl_history.append(current_entry)
    output["hitlHistory"] = hitl_history
    return output


def _inject_pending_metadata(
    execution_result: ExecutionResult,
    *,
    request_id: uuid.UUID,
    review_url: str,
    expires_at: datetime,
) -> None:
    pending_payload = {
        "decision": None,
        "summary": execution_result.pending_review.get("summary", ""),
        "draftText": execution_result.pending_review.get("draft_text", ""),
        "reviewUrl": review_url,
        "requestId": str(request_id),
        "expiresAt": expires_at.isoformat(),
        "shareText": build_hitl_share_text(
            execution_result.pending_review.get("summary", ""), review_url
        ),
        "shareMarkdown": build_hitl_share_markdown(
            execution_result.pending_review.get("summary", ""), review_url
        ),
    }
    hitl_history = execution_result.pending_review.get("history")
    if isinstance(hitl_history, list) and hitl_history:
        pending_payload["hitlHistory"] = copy.deepcopy(hitl_history)
    execution_result.outputs = {
        execution_result.resume_snapshot["paused_node_label"]: copy.deepcopy(pending_payload)
    }
    for node_result in execution_result.node_results:
        if (
            isinstance(node_result, dict)
            and node_result.get("node_id") == execution_result.resume_snapshot["paused_node_id"]
            and node_result.get("status") == "pending"
        ):
            node_result["output"] = copy.deepcopy(pending_payload)


async def persist_pending_hitl_execution(
    *,
    db: AsyncSession,
    workflow: Workflow,
    enriched_inputs: dict,
    execution_result: ExecutionResult,
    trigger_source: str | None,
    credentials_owner_id: uuid.UUID,
    trace_user_id: uuid.UUID | None,
    public_base_url: str,
    history_entry: ExecutionHistory | None = None,
) -> tuple[ExecutionHistory, HITLRequest]:
    if execution_result.status != "pending":
        raise ValueError("persist_pending_hitl_execution requires a pending execution result")
    if not execution_result.pending_review or not execution_result.resume_snapshot:
        raise ValueError("Pending execution result is missing HITL metadata")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=HITL_TTL_HOURS)
    snapshot = copy.deepcopy(execution_result.resume_snapshot)
    snapshot["credentials_owner_id"] = str(credentials_owner_id)
    snapshot["trace_user_id"] = str(trace_user_id) if trace_user_id else None
    snapshot["trigger_source"] = trigger_source
    snapshot["public_base_url"] = public_base_url
    snapshot["hitl_resume_mode"] = (
        execution_result.pending_review.get("resume_mode") or "inject_output"
    )
    if execution_result.pending_review.get("agent_state") is not None:
        snapshot["hitl_agent_state"] = copy.deepcopy(
            execution_result.pending_review.get("agent_state")
        )
    if execution_result.pending_review.get("approved_tool_call") is not None:
        snapshot["hitl_approved_tool_call"] = copy.deepcopy(
            execution_result.pending_review.get("approved_tool_call")
        )

    if history_entry is None:
        history_entry = ExecutionHistory(
            workflow_id=workflow.id,
            inputs=enriched_inputs,
            outputs={},
            node_results=[],
            status="pending",
            execution_time_ms=execution_result.execution_time_ms,
            trigger_source=trigger_source,
        )
        db.add(history_entry)

    history_entry.status = "pending"
    history_entry.inputs = enriched_inputs
    history_entry.execution_time_ms = execution_result.execution_time_ms
    history_entry.trigger_source = trigger_source
    await db.flush()

    hitl_request = HITLRequest(
        workflow_id=workflow.id,
        execution_history_id=history_entry.id,
        public_token=secrets.token_urlsafe(32),
        workflow_name=workflow.name,
        agent_node_id=snapshot["paused_node_id"],
        agent_label=snapshot["paused_node_label"],
        summary=execution_result.pending_review.get("summary", ""),
        original_draft_text=execution_result.pending_review.get("draft_text", ""),
        original_agent_output=execution_result.pending_review.get("original_agent_output") or {},
        resolved_output={},
        execution_snapshot=snapshot,
        status="pending",
        expires_at=expires_at,
    )
    db.add(hitl_request)
    await db.flush()

    review_url = build_review_url(public_base_url, hitl_request.public_token)
    _inject_pending_metadata(
        execution_result,
        request_id=hitl_request.id,
        review_url=review_url,
        expires_at=expires_at,
    )
    pending_payload = copy.deepcopy(
        execution_result.outputs.get(execution_result.resume_snapshot["paused_node_label"]) or {}
    )

    from app.api.workflows import get_credentials_context
    from app.services.global_variables_service import get_global_variables_context

    credentials_context = await get_credentials_context(db, credentials_owner_id)
    global_variables_context = await get_global_variables_context(db, credentials_owner_id)
    notification_branch_result = await asyncio.to_thread(
        execute_hitl_notification_branch,
        snapshot=snapshot,
        pending_output=pending_payload,
        credentials_context=credentials_context,
        global_variables_context=global_variables_context,
        trace_user_id=trace_user_id,
    )
    execution_result.node_results.extend(notification_branch_result.get("node_results") or [])
    updated_snapshot = notification_branch_result.get("resume_snapshot")
    if isinstance(updated_snapshot, dict):
        merged_snapshot = copy.deepcopy(updated_snapshot)
        for key in (
            "credentials_owner_id",
            "trace_user_id",
            "trigger_source",
            "public_base_url",
            "hitl_resume_mode",
            "hitl_agent_state",
            "hitl_approved_tool_call",
        ):
            if key in snapshot:
                merged_snapshot[key] = copy.deepcopy(snapshot[key])
        execution_result.resume_snapshot = merged_snapshot
        hitl_request.execution_snapshot = copy.deepcopy(merged_snapshot)
    execution_result.execution_time_ms += float(
        notification_branch_result.get("execution_time_ms") or 0
    )

    history_entry.outputs = copy.deepcopy(execution_result.outputs)
    history_entry.node_results = copy.deepcopy(execution_result.node_results)
    history_entry.execution_time_ms = execution_result.execution_time_ms
    return history_entry, hitl_request


async def get_hitl_request_by_token(db: AsyncSession, token: str) -> HITLRequest | None:
    result = await db.execute(select(HITLRequest).where(HITLRequest.public_token == token))
    hitl_request = result.scalar_one_or_none()
    if hitl_request is None:
        return None

    if hitl_request.status == "pending" and hitl_request.expires_at < datetime.now(timezone.utc):
        hitl_request.status = "expired"
        await db.flush()

    return hitl_request


async def resume_hitl_request_in_background(request_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        result = await db.execute(select(HITLRequest).where(HITLRequest.id == request_id))
        hitl_request = result.scalar_one_or_none()
        if hitl_request is None:
            return

        workflow = await db.get(Workflow, hitl_request.workflow_id)
        history_entry = await db.get(ExecutionHistory, hitl_request.execution_history_id)
        if workflow is None or history_entry is None:
            return

        snapshot = copy.deepcopy(hitl_request.execution_snapshot or {})
        credentials_owner_value = snapshot.get("credentials_owner_id")
        if not credentials_owner_value:
            hitl_request.resume_error = "Missing credentials_owner_id in HITL snapshot"
            await db.commit()
            return

        credentials_owner_id = uuid.UUID(str(credentials_owner_value))
        trace_user_value = snapshot.get("trace_user_id")
        trace_user_id = uuid.UUID(str(trace_user_value)) if trace_user_value else None
        public_base_url = snapshot.get("public_base_url") or ""
        trigger_source = snapshot.get("trigger_source")
        resolved_output = build_hitl_resolved_output(hitl_request)
        hitl_request.resolved_output = copy.deepcopy(resolved_output)
        hitl_request.resume_error = None

        from app.api.workflows import (
            _persist_global_variables_from_execution,
            get_credentials_context,
        )
        from app.services.global_variables_service import get_global_variables_context

        credentials_context = await get_credentials_context(db, credentials_owner_id)
        global_variables_context = await get_global_variables_context(db, credentials_owner_id)

        try:
            resumed_result = await asyncio.to_thread(
                resume_workflow_execution,
                snapshot=snapshot,
                resolved_output=resolved_output,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=trace_user_id,
            )
        except Exception as exc:
            hitl_request.resume_error = str(exc)
            history_entry.status = "error"
            history_entry.outputs = {"error": str(exc)}
            history_entry.execution_time_ms = 0
            await db.commit()
            return

        if resumed_result.status == "pending":
            await persist_pending_hitl_execution(
                db=db,
                workflow=workflow,
                enriched_inputs=history_entry.inputs,
                execution_result=resumed_result,
                trigger_source=trigger_source,
                credentials_owner_id=credentials_owner_id,
                trace_user_id=trace_user_id,
                public_base_url=public_base_url,
                history_entry=history_entry,
            )
            await db.commit()
            return

        history_entry.status = resumed_result.status
        history_entry.outputs = copy.deepcopy(resumed_result.outputs)
        history_entry.node_results = copy.deepcopy(resumed_result.node_results)
        history_entry.execution_time_ms = resumed_result.execution_time_ms

        await _persist_global_variables_from_execution(
            db,
            credentials_owner_id,
            snapshot.get("nodes") or [],
            snapshot.get("workflow_cache") or {},
            resumed_result.node_results,
            resumed_result.sub_workflow_executions,
        )
        await db.commit()


def ensure_hitl_request_is_actionable(hitl_request: HITLRequest) -> None:
    now = datetime.now(timezone.utc)
    if hitl_request.status == "expired" or hitl_request.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Review link has expired")
    if hitl_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review request has already been resolved",
        )
