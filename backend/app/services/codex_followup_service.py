from __future__ import annotations

import asyncio
import copy
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import CodexFollowupRequest, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.workflow_executor import (
    ExecutionResult,
    execute_hitl_notification_branch,
    resume_workflow_execution,
)

CODEX_FOLLOWUP_TTL_HOURS = 168


def is_codex_pending_execution(execution_result: ExecutionResult) -> bool:
    pending = execution_result.pending_review or {}
    return isinstance(pending, dict) and pending.get("kind") == "codex"


def build_public_base_url(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    if settings.frontend_url.strip():
        return settings.frontend_url.rstrip("/")
    for origin_value in settings.cors_origins_list:
        cleaned_origin = origin_value.strip()
        if cleaned_origin:
            return cleaned_origin.rstrip("/")
    return "http://localhost:4017"


def build_codex_followup_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/codex/followup/{token}"


def build_codex_share_text(question: str, followup_url: str) -> str:
    cleaned_question = question.strip()
    if cleaned_question:
        return f"Codex needs input: {cleaned_question}\nAnswer link: {followup_url}"
    return f"Codex needs input.\nAnswer link: {followup_url}"


def build_codex_share_markdown(question: str, followup_url: str) -> str:
    cleaned_question = question.strip()
    if cleaned_question:
        return f"Codex needs input: {cleaned_question}\n\n[Open answer page]({followup_url})"
    return f"Codex needs input.\n\n[Open answer page]({followup_url})"


def ensure_codex_followup_is_viewable(followup: CodexFollowupRequest) -> None:
    now = datetime.now(timezone.utc)
    if followup.status == "expired" or followup.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Codex link has expired")
    if followup.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This Codex follow-up has already been answered.",
        )


def ensure_codex_followup_is_actionable(followup: CodexFollowupRequest) -> None:
    now = datetime.now(timezone.utc)
    if followup.status == "expired" or followup.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Codex link has expired")
    if followup.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Codex follow-up has already been answered",
        )


def build_codex_answer_output(followup: CodexFollowupRequest) -> dict:
    return {
        "status": "answered",
        "summary": followup.summary,
        "question": followup.question,
        "answerText": followup.answer_text or "",
        "requestId": str(followup.id),
        "threadId": followup.thread_id,
        "workspacePath": followup.workspace_path,
        "branchName": followup.branch_name,
        "baseBranch": followup.base_branch,
        "repositoryUrl": followup.repository_url,
    }


def _inject_pending_metadata(
    execution_result: ExecutionResult,
    *,
    request_id: uuid.UUID,
    answer_url: str,
    expires_at: datetime,
) -> None:
    pending = execution_result.pending_review or {}
    question = str(pending.get("question") or "").strip()
    pending_payload = {
        "status": "needs_input",
        "summary": str(pending.get("summary") or "Codex needs input.").strip(),
        "question": question,
        "answerUrl": answer_url,
        "requestId": str(request_id),
        "expiresAt": expires_at.isoformat(),
        "shareText": build_codex_share_text(question, answer_url),
        "shareMarkdown": build_codex_share_markdown(question, answer_url),
        "threadId": pending.get("thread_id"),
        "workspacePath": pending.get("workspace_path"),
        "branchName": pending.get("branch_name"),
    }
    paused_label = execution_result.resume_snapshot["paused_node_label"]
    paused_node_id = execution_result.resume_snapshot["paused_node_id"]
    execution_result.outputs = {paused_label: copy.deepcopy(pending_payload)}
    for node_result in execution_result.node_results:
        if (
            isinstance(node_result, dict)
            and node_result.get("node_id") == paused_node_id
            and node_result.get("status") == "pending"
        ):
            node_result["output"] = copy.deepcopy(pending_payload)


async def persist_pending_codex_followup_execution(
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
) -> tuple[ExecutionHistory, CodexFollowupRequest]:
    if execution_result.status != "pending":
        raise ValueError("persist_pending_codex_followup_execution requires a pending result")
    if not execution_result.pending_review or not execution_result.resume_snapshot:
        raise ValueError("Pending execution result is missing Codex metadata")

    pending = execution_result.pending_review
    expires_at = datetime.now(timezone.utc) + timedelta(hours=CODEX_FOLLOWUP_TTL_HOURS)
    snapshot = copy.deepcopy(execution_result.resume_snapshot)
    snapshot["actor_user_id"] = snapshot.get("actor_user_id") or str(credentials_owner_id)
    snapshot["credentials_owner_id"] = str(credentials_owner_id)
    snapshot["trace_user_id"] = str(trace_user_id) if trace_user_id else None
    snapshot["trigger_source"] = trigger_source
    snapshot["public_base_url"] = public_base_url
    snapshot["hitl_resume_mode"] = "rerun_agent"

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

    followup = CodexFollowupRequest(
        workflow_id=workflow.id,
        execution_history_id=history_entry.id,
        public_token=secrets.token_urlsafe(32),
        workflow_name=workflow.name,
        codex_node_id=snapshot["paused_node_id"],
        codex_label=snapshot["paused_node_label"],
        summary=str(pending.get("summary") or "Codex needs input.").strip(),
        question=str(pending.get("question") or "").strip(),
        task_prompt=str(pending.get("task_prompt") or ""),
        repository_url=str(pending.get("repository_url") or ""),
        base_branch=str(pending.get("base_branch") or "main"),
        branch_name=str(pending.get("branch_name") or ""),
        thread_id=str(pending.get("thread_id") or "").strip() or None,
        workspace_path=str(pending.get("workspace_path") or "").strip() or None,
        original_output=pending.get("original_output") or {},
        resolved_output={},
        execution_snapshot=snapshot,
        status="pending",
        expires_at=expires_at,
    )
    db.add(followup)
    await db.flush()

    answer_url = build_codex_followup_url(public_base_url, followup.public_token)
    _inject_pending_metadata(
        execution_result,
        request_id=followup.id,
        answer_url=answer_url,
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
        source_handle="question",
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
        ):
            if key in snapshot:
                merged_snapshot[key] = copy.deepcopy(snapshot[key])
        execution_result.resume_snapshot = merged_snapshot
        followup.execution_snapshot = copy.deepcopy(merged_snapshot)
    execution_result.execution_time_ms += float(
        notification_branch_result.get("execution_time_ms") or 0
    )

    history_entry.outputs = copy.deepcopy(execution_result.outputs)
    history_entry.node_results = copy.deepcopy(execution_result.node_results)
    history_entry.execution_time_ms = execution_result.execution_time_ms
    return history_entry, followup


async def get_codex_followup_by_token(db: AsyncSession, token: str) -> CodexFollowupRequest | None:
    result = await db.execute(
        select(CodexFollowupRequest).where(CodexFollowupRequest.public_token == token)
    )
    followup = result.scalar_one_or_none()
    if followup is None:
        return None
    if followup.status == "pending" and followup.expires_at < datetime.now(timezone.utc):
        followup.status = "expired"
        await db.flush()
    return followup


async def resume_codex_followup_in_background(request_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        result = await db.execute(
            select(CodexFollowupRequest).where(CodexFollowupRequest.id == request_id)
        )
        followup = result.scalar_one_or_none()
        if followup is None or followup.status != "answered" or not followup.answer_text:
            return

        workflow = await db.get(Workflow, followup.workflow_id)
        history_entry = await db.get(ExecutionHistory, followup.execution_history_id)
        if workflow is None or history_entry is None:
            return

        snapshot = copy.deepcopy(followup.execution_snapshot or {})
        credentials_owner_value = snapshot.get("credentials_owner_id")
        if not credentials_owner_value:
            followup.resume_error = "Missing credentials_owner_id in Codex snapshot"
            await db.commit()
            return

        credentials_owner_id = uuid.UUID(str(credentials_owner_value))
        trace_user_value = snapshot.get("trace_user_id")
        trace_user_id = uuid.UUID(str(trace_user_value)) if trace_user_value else None
        public_base_url = snapshot.get("public_base_url") or ""
        trigger_source = snapshot.get("trigger_source")
        resolved_output = build_codex_answer_output(followup)
        followup.resolved_output = copy.deepcopy(resolved_output)
        followup.resume_error = None

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
            followup.resume_error = str(exc)
            history_entry.status = "error"
            history_entry.outputs = {"error": str(exc)}
            history_entry.execution_time_ms = 0
            await db.commit()
            return

        if resumed_result.status == "pending":
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
                from app.services.hitl_service import persist_pending_hitl_execution

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
