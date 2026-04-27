"""Telegram Bot API webhook endpoint."""

import asyncio
import hmac
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

logger = logging.getLogger("telegram_webhook")

router = APIRouter()

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-telegram-bot-api-secret-token",
        "x-execution-token",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-session-token",
    }
)


def _extract_primary_message(update: dict[str, Any]) -> dict[str, Any]:
    """Return the most useful message-like payload from a Telegram update."""
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        payload = update.get(key)
        if isinstance(payload, dict):
            return payload

    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        callback_message = callback_query.get("message")
        if isinstance(callback_message, dict):
            return callback_message

    return {}


def _sanitize_headers(headers: Any) -> dict[str, str]:
    """Strip sensitive transport headers before exposing them to downstream nodes."""
    safe_headers: dict[str, str] = {}
    for key, value in headers.items():
        normalized = key.lower()
        if normalized in _SENSITIVE_HEADERS:
            continue
        safe_headers[normalized] = value
    return safe_headers


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


async def _get_telegram_config(db: AsyncSession, credential_id: str) -> dict[str, Any] | None:
    """Return decrypted config from a telegram credential."""
    try:
        cred_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return None

    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.type == CredentialType.telegram,
        )
    )
    credential = result.scalar_one_or_none()
    if not credential:
        return None

    return decrypt_config(credential.encrypted_config)


async def _execute_workflow_background(
    workflow: Workflow,
    node_id: str,
    update_body: dict[str, Any],
    safe_headers: dict[str, str],
) -> None:
    """Run workflow execution after returning 200 to Telegram."""
    logger.info("Executing workflow %s via Telegram trigger node %s", workflow.id, node_id)

    try:
        inputs: dict[str, Any] = {
            "triggered_by": "telegram",
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "update": update_body,
            "message": _extract_primary_message(update_body),
            "callback_query": update_body.get("callback_query", {}),
            "headers": safe_headers,
        }

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                logger.error("Workflow %s not found for Telegram execution", workflow.id)
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
                trigger_source="telegram",
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
                "Workflow %s executed via Telegram trigger, status: %s",
                workflow.id,
                result.status,
            )

    except Exception:
        logger.exception(
            "Failed to execute workflow %s via Telegram trigger node %s",
            workflow.id,
            node_id,
        )


@router.post("/webhook/{node_id}")
async def telegram_webhook(node_id: str, request: Request) -> dict[str, Any]:
    """Receive Telegram webhook updates and dispatch matching workflows."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    async with async_session_maker() as db:
        workflow = await _find_workflow_by_node_id(db, node_id)

    if not workflow:
        logger.warning("No workflow found for Telegram trigger node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workflow found for this webhook URL",
        )

    trigger_node = next((node for node in workflow.nodes if node.get("id") == node_id), None)
    credential_id = None
    if trigger_node:
        credential_id = trigger_node.get("data", {}).get("credentialId") or None

    if credential_id:
        async with async_session_maker() as db:
            telegram_config = await _get_telegram_config(db, credential_id)

        if telegram_config:
            secret_token = str(telegram_config.get("secret_token") or "").strip()
            if secret_token:
                incoming_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
                if not incoming_secret or not hmac.compare_digest(secret_token, incoming_secret):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Invalid Telegram secret token",
                    )

    safe_headers = _sanitize_headers(request.headers)
    asyncio.create_task(_execute_workflow_background(workflow, node_id, body, safe_headers))
    return {"ok": True}
