"""Cal.com webhook endpoint for workflow triggers."""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import Credential, CredentialType, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.encryption import decrypt_config
from app.services.global_variables_service import get_global_variables_context
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger("cal_webhook")

router = APIRouter()

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-cal-signature-256",
        "x-execution-token",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-session-token",
    }
)


def _verify_cal_signature(webhook_secret: str, raw_body: bytes, signature: str) -> bool:
    """Verify the Cal.com HMAC-SHA256 signature for a raw webhook body."""
    normalized_signature = signature.strip().lower()
    if normalized_signature.startswith("sha256="):
        normalized_signature = normalized_signature.removeprefix("sha256=")
    if not normalized_signature:
        return False
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, normalized_signature)


async def _find_workflow_by_node_id(db: AsyncSession, node_id: str) -> Workflow | None:
    """Find the workflow containing the requested Cal.com Trigger node."""
    result = await db.execute(
        select(Workflow).where(
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps([{"id": node_id, "type": "calTrigger"}])
            )
        )
    )
    return result.scalar_one_or_none()


async def _get_webhook_secret(db: AsyncSession, credential_id: str) -> str | None:
    """Decrypt a Cal.com Trigger credential and return its webhook secret."""
    try:
        credential_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        select(Credential).where(
            Credential.id == credential_uuid,
            Credential.type == CredentialType.cal_trigger,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        return None
    config = decrypt_config(credential.encrypted_config)
    webhook_secret = str(config.get("webhook_secret") or "").strip()
    return webhook_secret or None


async def _execute_workflow_background(
    workflow: Workflow,
    node_id: str,
    event_body: dict[str, Any],
    safe_headers: dict[str, str],
) -> None:
    """Execute a workflow after acknowledging a verified Cal.com webhook."""
    logger.info("Executing workflow %s via Cal.com trigger node %s", workflow.id, node_id)
    try:
        inputs: dict[str, Any] = {
            "triggered_by": "Cal.com",
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "event": event_body,
            "trigger_event": event_body.get("triggerEvent"),
            "payload": event_body.get("payload", {}),
            "headers": safe_headers,
        }

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if fresh_workflow is None:
                logger.error("Workflow %s not found for Cal.com execution", workflow.id)
                return

            workflow_cache = await collect_referenced_workflows(
                db,
                fresh_workflow.nodes,
                actor_user_id=fresh_workflow.owner_id,
            )
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db,
                fresh_workflow.owner_id,
            )

            from app.services.execution_cancellation import clear_execution, register_execution

            execution_id = uuid.uuid4()
            cancel_event = register_execution(
                workflow_id=fresh_workflow.id,
                execution_id=execution_id,
                inputs=inputs,
                trigger_source="cal.com",
                actor_user_id=fresh_workflow.owner_id,
            )
            try:
                result = execute_workflow(
                    workflow_id=fresh_workflow.id,
                    nodes=fresh_workflow.nodes,
                    edges=fresh_workflow.edges,
                    inputs=inputs,
                    workflow_cache=workflow_cache,
                    credentials_context=credentials_context,
                    global_variables_context=global_variables_context,
                    trace_user_id=fresh_workflow.owner_id,
                    actor_user_id=fresh_workflow.owner_id,
                    cancel_event=cancel_event,
                    execution_id=str(execution_id),
                )
            finally:
                clear_execution(execution_id)

            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=fresh_workflow.id,
                    inputs=inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source="Cal.com",
                )
            )
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=fresh_workflow.id,
                owner_id=fresh_workflow.owner_id,
                workflow_name_snapshot=fresh_workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )

            for sub_execution in result.sub_workflow_executions:
                db.add(
                    ExecutionHistory(
                        workflow_id=uuid.UUID(sub_execution.workflow_id),
                        inputs=sub_execution.inputs,
                        outputs=sub_execution.outputs,
                        node_results=sub_execution.node_results,
                        status=sub_execution.status,
                        execution_time_ms=sub_execution.execution_time_ms,
                        trigger_source=sub_execution.trigger_source,
                    )
                )
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_execution.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_execution.workflow_name or "Sub-workflow",
                    status=sub_execution.status,
                    execution_time_ms=sub_execution.execution_time_ms,
                )

            await _persist_global_variables_from_execution(
                db,
                fresh_workflow.owner_id,
                fresh_workflow.nodes,
                workflow_cache,
                result.node_results,
                result.sub_workflow_executions,
            )
            await db.commit()
            logger.info(
                "Workflow %s executed via Cal.com trigger, status: %s",
                workflow.id,
                result.status,
            )
    except Exception:
        logger.exception(
            "Failed to execute workflow %s via Cal.com trigger node %s",
            workflow.id,
            node_id,
        )


@router.post("/webhook/{node_id}")
async def cal_webhook(node_id: str, request: Request) -> dict[str, bool]:
    """Verify a Cal.com webhook and schedule its workflow for execution."""
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    async with async_session_maker() as db:
        workflow = await _find_workflow_by_node_id(db, node_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workflow found for this webhook URL",
        )

    trigger_node = next(
        (
            node
            for node in workflow.nodes
            if node.get("id") == node_id and node.get("type") == "calTrigger"
        ),
        None,
    )
    credential_id = (
        str(trigger_node.get("data", {}).get("credentialId") or "").strip() if trigger_node else ""
    )
    if not credential_id:
        logger.warning("Cal.com webhook rejected: no credential on node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid webhook credential configuration",
        )

    async with async_session_maker() as db:
        webhook_secret = await _get_webhook_secret(db, credential_id)
    if not webhook_secret:
        logger.warning(
            "Cal.com webhook rejected: invalid credential_id=%s on node_id=%s",
            credential_id,
            node_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid webhook credential configuration",
        )

    signature = request.headers.get("x-cal-signature-256", "")
    if not _verify_cal_signature(webhook_secret, raw_body, signature):
        logger.warning("Invalid Cal.com signature for node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Cal.com signature",
        )

    safe_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _SENSITIVE_HEADERS
    }
    asyncio.create_task(_execute_workflow_background(workflow, node_id, body, safe_headers))
    return {"ok": True}
