"""Slack Events API webhook endpoint.

Handles URL verification challenge and routes events to workflow execution.
"""

import asyncio
import hashlib
import hmac
import logging
import time
import uuid
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

logger = logging.getLogger("slack_webhook")

router = APIRouter()

_SLACK_TIMESTAMP_TOLERANCE_SECONDS = 300

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-slack-signature",
        "x-execution-token",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-session-token",
    }
)


def _verify_slack_signature(
    signing_secret: str,
    raw_body: bytes,
    timestamp: str,
    signature: str,
) -> bool:
    """Verify X-Slack-Signature HMAC-SHA256. Returns True if valid."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > _SLACK_TIMESTAMP_TOLERANCE_SECONDS:
        return False
    base_string = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    expected = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


async def _find_workflow_by_node_id(
    db: AsyncSession,
    node_id: str,
) -> Workflow | None:
    """Use JSONB containment to find the workflow containing this node_id."""
    safe_node_id = node_id.replace("'", "").replace('"', "")
    result = await db.execute(
        select(Workflow).where(text(f'nodes::jsonb @> \'[{{"id": "{safe_node_id}"}}]\'::jsonb'))
    )
    return result.scalar_one_or_none()


async def _get_signing_secret(db: AsyncSession, credential_id: str) -> str | None:
    """Decrypt and return the signing_secret from a slack_trigger credential."""
    try:
        cred_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.type == CredentialType.slack_trigger,
        )
    )
    credential = result.scalar_one_or_none()
    if not credential:
        return None
    config = decrypt_config(credential.encrypted_config)
    return config.get("signing_secret")


async def _execute_workflow_background(
    workflow: Workflow,
    node_id: str,
    event_body: dict[str, Any],
    safe_headers: dict[str, str],
) -> None:
    """Run workflow execution as a background task after returning 200 to Slack."""
    logger.info("Executing workflow %s via Slack trigger node %s", workflow.id, node_id)
    try:
        inputs: dict[str, Any] = {
            "triggered_by": "Slack",
            "trigger_node_id": node_id,
            "event": event_body,
            "headers": safe_headers,
        }

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                logger.error("Workflow %s not found for Slack execution", workflow.id)
                return

            workflow_cache = await collect_referenced_workflows(db, fresh_workflow.nodes)
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            result = execute_workflow(
                workflow_id=fresh_workflow.id,
                nodes=fresh_workflow.nodes,
                edges=fresh_workflow.edges,
                inputs=inputs,
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=fresh_workflow.owner_id,
            )

            history_entry = ExecutionHistory(
                workflow_id=fresh_workflow.id,
                inputs=inputs,
                outputs=result.outputs,
                node_results=result.node_results,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                trigger_source="Slack",
            )
            db.add(history_entry)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=fresh_workflow.id,
                owner_id=fresh_workflow.owner_id,
                workflow_name_snapshot=fresh_workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )

            for sub_exec in result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=sub_exec.inputs,
                    outputs=sub_exec.outputs,
                    node_results=sub_exec.node_results,
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                )
                db.add(sub_history)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
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
                "Workflow %s executed via Slack trigger, status: %s",
                workflow.id,
                result.status,
            )

    except Exception:
        logger.exception(
            "Failed to execute workflow %s via Slack trigger node %s",
            workflow.id,
            node_id,
        )


@router.post("/webhook/{node_id}")
async def slack_webhook(node_id: str, request: Request) -> dict[str, Any]:
    """Receive Slack Events API webhooks.

    Handles:
    - url_verification challenge: responds immediately, no workflow execution.
    - Signature verification via slackTrigger credential.
    - Workflow execution as a background task (Slack requires 200 within 3s).
    """
    raw_body = await request.body()

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    # Handle Slack URL verification challenge immediately — no workflow execution
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info("Slack URL verification challenge received for node %s", node_id)
        return {"challenge": challenge}

    async with async_session_maker() as db:
        workflow = await _find_workflow_by_node_id(db, node_id)

    if not workflow:
        logger.warning("No workflow found for Slack trigger node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workflow found for this webhook URL",
        )

    # Find the trigger node's credentialId
    trigger_node = next(
        (n for n in workflow.nodes if n.get("id") == node_id),
        None,
    )
    credential_id: str | None = None
    if trigger_node:
        credential_id = trigger_node.get("data", {}).get("credentialId") or None

    # Verify Slack signature if credential is configured
    if credential_id:
        async with async_session_maker() as db:
            signing_secret = await _get_signing_secret(db, credential_id)

        if signing_secret:
            timestamp = request.headers.get("x-slack-request-timestamp", "")
            signature = request.headers.get("x-slack-signature", "")
            if not _verify_slack_signature(signing_secret, raw_body, timestamp, signature):
                logger.warning(
                    "Invalid Slack signature for node_id=%s",
                    node_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid Slack signature",
                )
    else:
        logger.warning(
            "No credential configured for Slack trigger node_id=%s — running without verification",
            node_id,
        )

    # Build safe headers (strip sensitive ones)
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in _SENSITIVE_HEADERS}

    # Fire workflow execution as background task — Slack requires 200 within 3s
    asyncio.create_task(_execute_workflow_background(workflow, node_id, body, safe_headers))

    return {"ok": True}
