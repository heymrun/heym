"""Discord Interactions API webhook endpoint.

Handles PING verification, Ed25519 signature validation, and routes
interactions to workflow execution.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
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

logger = logging.getLogger("discord_webhook")

router = APIRouter()

_DISCORD_TIMESTAMP_TOLERANCE_SECONDS = 300
_INTERACTION_PING = 1
_RESPONSE_PONG = 1
_RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5
_DISCORD_MESSAGE_MAX_LENGTH = 2000

_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-signature-ed25519",
        "x-signature-timestamp",
        "x-execution-token",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-session-token",
    }
)


def _normalize_public_key_hex(public_key: str) -> str:
    """Strip whitespace and lowercase a Discord application public key."""
    return public_key.strip().replace(" ", "").lower()


def _truncate_discord_content(content: str) -> str:
    """Clamp outbound Discord content to the platform message limit."""
    trimmed = content.strip()
    if len(trimmed) <= _DISCORD_MESSAGE_MAX_LENGTH:
        return trimmed
    return trimmed[: _DISCORD_MESSAGE_MAX_LENGTH - 3].rstrip() + "..."


def _coerce_discord_followup_content(value: Any) -> str | None:
    """Convert workflow outputs into a user-visible Discord follow-up message."""
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return _truncate_discord_content(trimmed) if trimmed else None
    if isinstance(value, (bool, int, float)):
        return _truncate_discord_content(str(value))
    if isinstance(value, dict):
        for key in ("result", "content", "message", "text", "error"):
            if key in value:
                return _coerce_discord_followup_content(value.get(key))
        serialized = json.dumps(value, ensure_ascii=False)
        if serialized not in {"{}", "[]", '""'}:
            return _truncate_discord_content(serialized)
        return None
    if isinstance(value, list):
        if not value:
            return None
        return _truncate_discord_content(json.dumps(value, ensure_ascii=False))
    return _truncate_discord_content(str(value))


def _extract_discord_followup_content(workflow_outputs: dict[str, Any]) -> str | None:
    """Choose the best follow-up body from final workflow outputs."""
    if not workflow_outputs:
        return None
    if len(workflow_outputs) == 1:
        return _coerce_discord_followup_content(next(iter(workflow_outputs.values())))
    return _coerce_discord_followup_content(workflow_outputs)


async def _send_discord_followup_message(
    interaction_body: dict[str, Any],
    workflow_outputs: dict[str, Any],
) -> None:
    """Send the final workflow output back to the deferred Discord interaction."""
    application_id = str(interaction_body.get("application_id") or "").strip()
    interaction_token = str(interaction_body.get("token") or "").strip()
    if not application_id or not interaction_token:
        logger.info("Discord interaction missing application_id or token; skipping follow-up")
        return

    content = _extract_discord_followup_content(workflow_outputs)
    if not content:
        logger.info("Workflow produced no usable Discord follow-up content")
        return

    followup_url = f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(followup_url, json={"content": content})
        if response.status_code >= 400:
            logger.warning(
                "Discord follow-up failed with status %s: %s",
                response.status_code,
                response.text,
            )
            return

    logger.info("Discord follow-up sent successfully")


def _verify_discord_signature(
    public_key_hex: str,
    signature_hex: str,
    timestamp: str,
    raw_body: bytes,
) -> bool:
    """Verify Discord interaction signature (Ed25519). Returns True if valid."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > _DISCORD_TIMESTAMP_TOLERANCE_SECONDS:
        return False

    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(_normalize_public_key_hex(public_key_hex))
        )
        message = timestamp.encode("utf-8") + raw_body
        public_key.verify(bytes.fromhex(signature_hex.strip()), message)
        return True
    except (InvalidSignature, ValueError):
        return False


async def _find_workflow_by_node_id(
    db: AsyncSession,
    node_id: str,
) -> Workflow | None:
    """Use JSONB containment to find the workflow containing this node_id."""
    result = await db.execute(
        select(Workflow).where(
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps([{"id": node_id}])
            )
        )
    )
    return result.scalar_one_or_none()


async def _get_public_key(db: AsyncSession, credential_id: str) -> str | None:
    """Decrypt and return the public_key from a discord_trigger credential."""
    try:
        cred_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.type == CredentialType.discord_trigger,
        )
    )
    credential = result.scalar_one_or_none()
    if not credential:
        return None
    config = decrypt_config(credential.encrypted_config)
    public_key = str(config.get("public_key", "")).strip()
    return public_key or None


async def _execute_workflow_background(
    workflow: Workflow,
    node_id: str,
    interaction_body: dict[str, Any],
    safe_headers: dict[str, str],
) -> None:
    """Run workflow execution after returning a deferred interaction response."""
    logger.info("Executing workflow %s via Discord trigger node %s", workflow.id, node_id)
    try:
        inputs: dict[str, Any] = {
            "triggered_by": "Discord",
            "trigger_node_id": node_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "interaction": interaction_body,
            "type": interaction_body.get("type"),
            "data": interaction_body.get("data", {}),
            "headers": safe_headers,
        }

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                logger.error("Workflow %s not found for Discord execution", workflow.id)
                return

            workflow_cache = await collect_referenced_workflows(
                db, fresh_workflow.nodes, actor_user_id=fresh_workflow.owner_id
            )
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            from app.services.execution_cancellation import clear_execution, register_execution

            execution_id = uuid.uuid4()
            cancel_event = register_execution(
                workflow_id=fresh_workflow.id,
                execution_id=execution_id,
                inputs=inputs,
                trigger_source="discord",
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
                )
            finally:
                clear_execution(execution_id)

            history_entry = ExecutionHistory(
                workflow_id=fresh_workflow.id,
                inputs=inputs,
                outputs=result.outputs,
                node_results=result.node_results,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                trigger_source="Discord",
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
                "Workflow %s executed via Discord trigger, status: %s",
                workflow.id,
                result.status,
            )
            await _send_discord_followup_message(interaction_body, result.outputs)

    except Exception:
        logger.exception(
            "Failed to execute workflow %s via Discord trigger node %s",
            workflow.id,
            node_id,
        )


@router.post("/webhook/{node_id}")
async def discord_webhook(node_id: str, request: Request) -> dict[str, Any]:
    """Receive Discord Interactions API webhooks.

    Handles:
    - Ed25519 signature verification via discordTrigger credential.
    - PING (type 1): responds with PONG after verification, no workflow execution.
    - Deferred interaction ack + background workflow execution.
    """
    raw_body = await request.body()

    try:
        body: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    async with async_session_maker() as db:
        workflow = await _find_workflow_by_node_id(db, node_id)

    if not workflow:
        logger.warning("No workflow found for Discord trigger node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workflow found for this webhook URL",
        )

    trigger_node = next(
        (node for node in workflow.nodes if node.get("id") == node_id),
        None,
    )
    credential_id: str | None = None
    if trigger_node:
        credential_id = trigger_node.get("data", {}).get("credentialId") or None

    if not credential_id:
        logger.warning(
            "Missing Discord trigger credential for node_id=%s",
            node_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord trigger credential is required",
        )

    async with async_session_maker() as db:
        public_key = await _get_public_key(db, credential_id)

    if not public_key:
        logger.warning(
            "Discord trigger credential %s for node_id=%s has no usable public key",
            credential_id,
            node_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord trigger credential is invalid or missing a public key",
        )

    signature = request.headers.get("x-signature-ed25519", "")
    timestamp = request.headers.get("x-signature-timestamp", "")
    if not _verify_discord_signature(public_key, signature, timestamp, raw_body):
        logger.warning("Invalid Discord signature for node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Discord signature",
        )

    interaction_type = body.get("type")
    if interaction_type == _INTERACTION_PING:
        logger.info("Discord PING received for node %s", node_id)
        return {"type": _RESPONSE_PONG}

    safe_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _SENSITIVE_HEADERS
    }

    asyncio.create_task(_execute_workflow_background(workflow, node_id, body, safe_headers))

    return {"type": _RESPONSE_DEFERRED_CHANNEL_MESSAGE}
