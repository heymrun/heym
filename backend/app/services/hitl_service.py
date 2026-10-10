import asyncio
import copy
import logging
import secrets
import uuid
from concurrent.futures import CancelledError
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.analytics import (
    resolve_execution_analytics_bucket,
    upsert_workflow_analytics_snapshot,
)
from app.config import settings
from app.db.models import ExecutionHistory, HITLRequest, Workflow
from app.db.session import async_session_maker
from app.services.workflow_executor import (
    ExecutionResult,
    WorkflowCancelledError,
    WorkflowTimeoutError,
    _to_json_compatible,
    execute_hitl_notification_branch,
    resume_workflow_execution,
)

logger = logging.getLogger(__name__)

HITL_TTL_HOURS = 168


def build_public_base_url(request: Request) -> str:
    """Return the public origin for capability-bearing links (review, download, upload).

    The request never decides it. ``Origin`` and ``X-Forwarded-*`` are client supplied, and
    a spoofed value would mint a live token on a host the attacker controls
    (GHSA-6rv3-wh25-7pg5). Deployments behind a reverse proxy configure ``FRONTEND_URL``,
    which is the same value the request-free triggers (cron, IMAP, queue workers) already use.
    """
    return build_default_public_base_url()


def build_default_public_base_url() -> str:
    """Return the configured public frontend URL for background executions."""
    if settings.frontend_url.strip():
        return settings.frontend_url.rstrip("/")
    for origin in settings.cors_origins_list:
        cleaned_origin = origin.strip()
        if cleaned_origin:
            return cleaned_origin.rstrip("/")
    return "http://localhost:4017"


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
    history_entry_id: uuid.UUID | None = None,
) -> tuple[ExecutionHistory, HITLRequest]:
    if execution_result.status != "pending":
        raise ValueError("persist_pending_hitl_execution requires a pending execution result")
    if not execution_result.pending_review or not execution_result.resume_snapshot:
        raise ValueError("Pending execution result is missing HITL metadata")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=HITL_TTL_HOURS)
    snapshot = copy.deepcopy(execution_result.resume_snapshot)
    snapshot["actor_user_id"] = snapshot.get("actor_user_id") or str(credentials_owner_id)
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

    has_known_bucket = bool(
        snapshot.get("analytics_bucket_time") or snapshot.get("analytics_bucket_start")
    )
    if history_entry is None:
        first_pause_at = datetime.now(timezone.utc)
        history_entry = ExecutionHistory(
            **({"id": history_entry_id} if history_entry_id is not None else {}),
            workflow_id=workflow.id,
            inputs=enriched_inputs,
            outputs={},
            node_results=[],
            status="pending",
            execution_time_ms=execution_result.execution_time_ms,
            trigger_source=trigger_source,
            started_at=first_pause_at,
        )
        db.add(history_entry)
        bucket_time_raw = (
            snapshot.get("analytics_bucket_time")
            or snapshot.get("analytics_bucket_start")
            or first_pause_at.isoformat()
        )
        bucket_time_str = (
            bucket_time_raw
            if isinstance(bucket_time_raw, str)
            else (
                bucket_time_raw.isoformat()
                if hasattr(bucket_time_raw, "isoformat")
                else str(bucket_time_raw)
            )
        )
        snapshot["analytics_bucket_time"] = bucket_time_str
        if isinstance(execution_result.resume_snapshot, dict):
            execution_result.resume_snapshot["analytics_bucket_time"] = bucket_time_str
    else:
        if history_entry.started_at is None:
            history_entry.started_at = datetime.now(timezone.utc)
        if has_known_bucket:
            bucket_time_raw = snapshot.get("analytics_bucket_time") or snapshot.get(
                "analytics_bucket_start"
            )
            bucket_time_str = (
                bucket_time_raw
                if isinstance(bucket_time_raw, str)
                else (
                    bucket_time_raw.isoformat()
                    if hasattr(bucket_time_raw, "isoformat")
                    else str(bucket_time_raw)
                )
            )
            snapshot["analytics_bucket_time"] = bucket_time_str
            if isinstance(execution_result.resume_snapshot, dict):
                execution_result.resume_snapshot["analytics_bucket_time"] = bucket_time_str
        else:
            snapshot.pop("analytics_bucket_time", None)
            snapshot.pop("analytics_bucket_start", None)
            if isinstance(execution_result.resume_snapshot, dict):
                execution_result.resume_snapshot.pop("analytics_bucket_time", None)
                execution_result.resume_snapshot.pop("analytics_bucket_start", None)

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
            "actor_user_id",
            "trace_user_id",
            "trigger_source",
            "public_base_url",
            "hitl_resume_mode",
            "hitl_agent_state",
            "hitl_approved_tool_call",
            "analytics_bucket_time",
        ):
            if key in snapshot:
                merged_snapshot[key] = copy.deepcopy(snapshot[key])
            elif key == "analytics_bucket_time":
                merged_snapshot.pop(key, None)
        merged_snapshot.pop("analytics_bucket_start", None)
        execution_result.resume_snapshot = merged_snapshot
        hitl_request.execution_snapshot = copy.deepcopy(merged_snapshot)
    execution_result.execution_time_ms += float(
        notification_branch_result.get("execution_time_ms") or 0
    )

    history_entry.outputs = copy.deepcopy(execution_result.outputs)
    history_entry.node_results = copy.deepcopy(execution_result.node_results)
    history_entry.execution_time_ms = execution_result.execution_time_ms
    return history_entry, hitl_request


def _owned_pending_filters(owner_id: uuid.UUID, now: datetime) -> tuple:
    return (
        Workflow.owner_id == owner_id,
        HITLRequest.status == "pending",
        HITLRequest.expires_at > now,
    )


async def list_pending_hitl_for_owner(
    db: AsyncSession, owner_id: uuid.UUID, *, limit: int = 100
) -> tuple[int, list[HITLRequest]]:
    """Return the pending-review count and the oldest reviews owned by this user.

    The count is the full queue. ``limit`` only caps the rows returned for the carousel.
    """
    now = datetime.now(timezone.utc)
    filters = _owned_pending_filters(owner_id, now)
    count_result = await db.execute(
        select(func.count())
        .select_from(HITLRequest)
        .join(Workflow, Workflow.id == HITLRequest.workflow_id)
        .where(*filters)
    )
    total = int(count_result.scalar_one())
    rows_result = await db.execute(
        select(HITLRequest)
        .join(Workflow, Workflow.id == HITLRequest.workflow_id)
        .where(*filters)
        .order_by(HITLRequest.created_at.asc())
        .limit(limit)
    )
    return total, list(rows_result.scalars().all())


async def get_owned_hitl_request(
    db: AsyncSession, request_id: uuid.UUID, owner_id: uuid.UUID
) -> HITLRequest:
    """Load a review only when the caller owns its workflow.

    A missing row and a row owned by someone else both 404, so an inbox id
    cannot be used to probe other people's reviews.
    """
    result = await db.execute(
        select(HITLRequest)
        .join(Workflow, Workflow.id == HITLRequest.workflow_id)
        .where(HITLRequest.id == request_id, Workflow.owner_id == owner_id)
    )
    hitl_request = result.scalar_one_or_none()
    if hitl_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found"
        )
    return hitl_request


async def get_hitl_request_by_token(db: AsyncSession, token: str) -> HITLRequest | None:
    result = await db.execute(select(HITLRequest).where(HITLRequest.public_token == token))
    hitl_request = result.scalar_one_or_none()
    if hitl_request is None:
        return None

    if hitl_request.status == "pending" and hitl_request.expires_at < datetime.now(timezone.utc):
        hitl_request.status = "expired"
        await db.flush()

    return hitl_request


def _hitl_agent_node(workflow: Workflow) -> tuple[str, str]:
    """The id and label of the agent step that waits for a person."""
    nodes = workflow.nodes if isinstance(workflow.nodes, list) else []
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "agent":
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if not data.get("hitlEnabled"):
            continue
        node_id = str(node.get("id") or "").strip()
        if node_id:
            return node_id, str(data.get("label") or "Review")
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="This workflow has no step waiting for a person",
    )


def _close_seeded_review(
    history_entry: ExecutionHistory, hitl_request: HITLRequest, snapshot: dict
) -> None:
    """Finish a planted review from its decision. There is no agent left to resume."""
    if hitl_request.decision == "refuse":
        history_entry.status = "error"
        history_entry.outputs = {"error": hitl_request.refusal_reason or "Refused"}
    else:
        label = str(snapshot.get("paused_node_label") or hitl_request.agent_label)
        text = (hitl_request.edited_text or hitl_request.original_draft_text or "").strip()
        history_entry.status = "success"
        history_entry.outputs = {label: {"text": text}}
    flag_modified(history_entry, "outputs")


async def seed_pending_workflow_review(
    db: AsyncSession,
    workflow: Workflow,
    *,
    owner_id: uuid.UUID,
    summary: str,
    draft_text: str,
    trigger_source: str | None,
    inputs: dict,
) -> tuple[HITLRequest, bool]:
    """Leave one review waiting on `workflow`, without running it.

    A review already waiting is returned as it is, so a second call does not add another.
    The history row is pending, which is what the inbox, the active-run list and a menu
    badge count. `created` is false when an existing review was returned.
    """
    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(
            select(HITLRequest)
            .where(
                HITLRequest.workflow_id == workflow.id,
                HITLRequest.status == "pending",
                HITLRequest.expires_at > now,
            )
            .order_by(HITLRequest.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    node_id, label = _hitl_agent_node(workflow)
    expires_at = now + timedelta(hours=HITL_TTL_HOURS)
    history_entry = ExecutionHistory(
        workflow_id=workflow.id,
        inputs=inputs,
        outputs={},
        node_results=[],
        status="pending",
        execution_time_ms=0,
        trigger_source=trigger_source,
        started_at=now,
    )
    db.add(history_entry)
    await db.flush()

    hitl_request = HITLRequest(
        workflow_id=workflow.id,
        execution_history_id=history_entry.id,
        public_token=secrets.token_urlsafe(32),
        workflow_name=workflow.name,
        agent_node_id=node_id,
        agent_label=label,
        summary=summary,
        original_draft_text=draft_text,
        original_agent_output={"text": draft_text},
        resolved_output={},
        execution_snapshot={
            "seeded_review": True,
            "credentials_owner_id": str(owner_id),
            "actor_user_id": str(owner_id),
            "trace_user_id": str(owner_id),
            "trigger_source": trigger_source,
            "paused_node_id": node_id,
            "paused_node_label": label,
        },
        status="pending",
        expires_at=expires_at,
    )
    db.add(hitl_request)
    await db.flush()

    review_url = build_review_url(build_default_public_base_url(), hitl_request.public_token)
    pending_payload = {
        "decision": None,
        "summary": summary,
        "draftText": draft_text,
        "reviewUrl": review_url,
        "requestId": str(hitl_request.id),
        "expiresAt": expires_at.isoformat(),
    }
    history_entry.outputs = {label: pending_payload}
    history_entry.node_results = [
        {
            "node_id": node_id,
            "node_label": label,
            "node_type": "agent",
            "status": "pending",
            "output": pending_payload,
            "execution_time_ms": 0,
        }
    ]
    flag_modified(history_entry, "outputs")
    flag_modified(history_entry, "node_results")
    return hitl_request, True


async def resume_hitl_request_in_background(request_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        result = await db.execute(select(HITLRequest).where(HITLRequest.id == request_id))
        hitl_request = result.scalar_one_or_none()
        if hitl_request is None:
            return
        if hitl_request.status != "resolved" or not hitl_request.decision:
            return

        workflow = await db.get(Workflow, hitl_request.workflow_id)
        history_entry = await db.get(ExecutionHistory, hitl_request.execution_history_id)
        if workflow is None or history_entry is None:
            return

        snapshot = copy.deepcopy(hitl_request.execution_snapshot or {})
        if snapshot.get("seeded_review"):
            # Planted for a demo: there is no paused agent to resume.
            _close_seeded_review(history_entry, hitl_request, snapshot)
            await db.commit()
            return
        credentials_owner_value = snapshot.get("credentials_owner_id")
        trigger_source = snapshot.get("trigger_source")
        effective_trigger_source = trigger_source or history_entry.trigger_source
        is_already_counted = effective_trigger_source not in ("board", "portal")
        has_known_bucket = bool(
            snapshot
            and isinstance(snapshot, dict)
            and (snapshot.get("analytics_bucket_time") or snapshot.get("analytics_bucket_start"))
        )
        try:
            analytics_bucket_time = await resolve_execution_analytics_bucket(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                candidate_time=hitl_request.created_at,
                snapshot=snapshot,
                history_started_at=history_entry.started_at,
                is_already_counted=is_already_counted,
            )

            if not credentials_owner_value:
                raise ValueError("Missing credentials_owner_id in HITL snapshot")

            credentials_owner_id = uuid.UUID(str(credentials_owner_value))
            trace_user_value = snapshot.get("trace_user_id")
            trace_user_id = uuid.UUID(str(trace_user_value)) if trace_user_value else None
            # Re-derived, never from the snapshot: pre-fix rows can carry a spoofed host.
            public_base_url = build_default_public_base_url()
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

            resumed_result = await asyncio.to_thread(
                resume_workflow_execution,
                snapshot=snapshot,
                resolved_output=resolved_output,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=trace_user_id,
            )

            if resumed_result.status == "pending":
                if isinstance(resumed_result.resume_snapshot, dict):
                    if (
                        "analytics_bucket_time" in snapshot
                        and "analytics_bucket_time" not in resumed_result.resume_snapshot
                    ):
                        resumed_result.resume_snapshot["analytics_bucket_time"] = snapshot[
                            "analytics_bucket_time"
                        ]
                    elif (
                        "analytics_bucket_start" in snapshot
                        and "analytics_bucket_start" not in resumed_result.resume_snapshot
                        and "analytics_bucket_time" not in resumed_result.resume_snapshot
                    ):
                        resumed_result.resume_snapshot["analytics_bucket_start"] = snapshot[
                            "analytics_bucket_start"
                        ]
                    else:
                        resumed_result.resume_snapshot.pop("analytics_bucket_time", None)
                        resumed_result.resume_snapshot.pop("analytics_bucket_start", None)

                from app.services.codex_followup_service import (
                    is_codex_pending_execution,
                    persist_pending_codex_followup_execution,
                )

                if is_codex_pending_execution(resumed_result):
                    await persist_pending_codex_followup_execution(
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
                else:
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

            if getattr(resumed_result, "allow_downstream_pending", False):
                try:
                    await asyncio.to_thread(resumed_result.join_allow_downstream)
                    if any(
                        isinstance(node_result, dict)
                        and node_result.get("status") == "error"
                        and node_result.get("metadata", {}).get("retry_stage") != "attempt_failed"
                        for node_result in (getattr(resumed_result, "node_results", None) or [])
                    ):
                        resumed_result.status = "error"
                except WorkflowTimeoutError as exc:
                    logger.warning(
                        "HITL resumed run %s allowDownstream timed out: %s", history_entry.id, exc
                    )
                    resumed_result.status = "error"
                    if hasattr(resumed_result, "outputs") and isinstance(
                        resumed_result.outputs, dict
                    ):
                        resumed_result.outputs.setdefault(
                            "error", str(exc) or "Workflow execution timed out"
                        )
                except (WorkflowCancelledError, CancelledError, asyncio.CancelledError):
                    logger.info("HITL resumed run %s allowDownstream cancelled", history_entry.id)
                    resumed_result.status = "cancelled"
                except Exception as exc:
                    logger.exception(
                        "HITL resumed run %s allowDownstream failed unexpectedly", history_entry.id
                    )
                    resumed_result.status = "error"
                    if hasattr(resumed_result, "outputs") and isinstance(
                        resumed_result.outputs, dict
                    ):
                        resumed_result.outputs.setdefault("error", str(exc))

            history_entry.status = resumed_result.status
            history_entry.outputs = _to_json_compatible(resumed_result.outputs)
            history_entry.node_results = _to_json_compatible(resumed_result.node_results)
            history_entry.execution_time_ms = resumed_result.execution_time_ms
            flag_modified(history_entry, "outputs")
            flag_modified(history_entry, "node_results")

            for sub_exec in resumed_result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(str(sub_exec.workflow_id)),
                    inputs=_to_json_compatible(sub_exec.inputs),
                    outputs=_to_json_compatible(sub_exec.outputs),
                    node_results=_to_json_compatible(sub_exec.node_results),
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                )
                db.add(sub_history)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(str(sub_exec.workflow_id)),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                )

            await _persist_global_variables_from_execution(
                db,
                credentials_owner_id,
                snapshot.get("nodes") or [],
                snapshot.get("workflow_cache") or {},
                resumed_result.node_results,
                resumed_result.sub_workflow_executions,
            )
            if analytics_bucket_time is not None:
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status=resumed_result.status,
                    execution_time_ms=resumed_result.execution_time_ms,
                    started_at=analytics_bucket_time,
                    count_execution=not is_already_counted,
                )
            await db.commit()
            await _resume_board_chain(history_entry.id)
        except Exception as exc:
            bucket_to_use = locals().get("analytics_bucket_time")
            if bucket_to_use is None and has_known_bucket:
                raw = snapshot.get("analytics_bucket_time") or snapshot.get(
                    "analytics_bucket_start"
                )
                if isinstance(raw, datetime):
                    bucket_to_use = raw
                elif isinstance(raw, str):
                    try:
                        bucket_to_use = datetime.fromisoformat(raw)
                    except (ValueError, TypeError):
                        bucket_to_use = None
            if bucket_to_use is None and not is_already_counted:
                bucket_to_use = (
                    history_entry.started_at
                    or hitl_request.created_at
                    or datetime.now(timezone.utc)
                )
            hitl_request.resume_error = str(exc)
            history_entry.status = "error"
            history_entry.outputs = {"error": str(exc)}
            history_entry.execution_time_ms = 0
            flag_modified(history_entry, "outputs")
            if bucket_to_use is not None:
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=workflow.id,
                    owner_id=workflow.owner_id,
                    workflow_name_snapshot=workflow.name,
                    status="error",
                    execution_time_ms=0.0,
                    started_at=bucket_to_use,
                    count_execution=not is_already_counted,
                )
            await db.commit()
            await _resume_board_chain(history_entry.id)
            return


async def _resume_board_chain(execution_history_id: uuid.UUID) -> None:
    """Let a board chain that paused on this execution carry on. No-op for other triggers."""
    from app.services.board_run_service import resume_card_chain

    await resume_card_chain(execution_history_id)


def ensure_hitl_request_is_actionable(hitl_request: HITLRequest) -> None:
    now = datetime.now(timezone.utc)
    if hitl_request.status == "expired" or hitl_request.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Review link has expired")
    if hitl_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review request has already been resolved",
        )


async def claim_hitl_request_for_decision(
    db: AsyncSession,
    hitl_request: HITLRequest,
    *,
    decision: str,
    edited_text: str | None,
    refusal_reason: str | None,
) -> bool:
    """Atomically claim a pending request for this decision.

    The status/expiry predicates live in the UPDATE itself, so exactly one
    concurrent caller can win; the loser sees rowcount 0 instead of silently
    overwriting the winner and scheduling a second resume.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(HITLRequest)
        .where(
            HITLRequest.id == hitl_request.id,
            HITLRequest.status == "pending",
            HITLRequest.expires_at > now,
        )
        .values(
            decision=decision,
            edited_text=edited_text,
            refusal_reason=refusal_reason,
            status="resolved",
            resolved_at=now,
            resume_error=None,
        )
    )
    return result.rowcount == 1


async def refresh_hitl_request_after_lost_claim(
    db: AsyncSession, hitl_request: HITLRequest
) -> HTTPException:
    """Map a lost claim to the same error a serialized caller would have seen.

    Re-reads only this row (populate_existing) instead of rolling back: the
    shared request session also holds the chat user, credentials, and any
    uncommitted work from earlier tool calls in the same turn, and rolling
    it back would break the rest of the request.
    """
    result = await db.execute(
        select(HITLRequest)
        .where(HITLRequest.id == hitl_request.id)
        .execution_options(populate_existing=True)
    )
    fresh = result.scalar_one_or_none()
    if fresh is None:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found"
        )
    now = datetime.now(timezone.utc)
    if fresh.status == "expired" or fresh.expires_at < now:
        return HTTPException(status_code=status.HTTP_410_GONE, detail="Review link has expired")
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Review request has already been resolved",
    )
