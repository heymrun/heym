"""Slack Events API webhook endpoint.

Handles URL verification challenge and routes events to workflow execution.
"""

import asyncio
import hashlib
import hmac
import json
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
from app.services.cluster.dispatch import dispatch_workflow, log_offloaded_run
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_default_public_base_url
from app.services.pending_execution import (
    needs_local_pending_persist,
    persist_pending_execution,
)

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
    result = await db.execute(
        select(Workflow).where(
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps([{"id": node_id}])
            )
        )
    )
    return result.scalar_one_or_none()


_ECHO_SUBTYPES = frozenset({"bot_message", "message_changed", "message_deleted"})


def _is_bot_echo(body: dict[str, Any]) -> bool:
    """Whether an event is a bot's own post or an edit, which a Slack Bot flow must not rerun on.

    A flow that replies in the channel it listens to would otherwise trigger itself forever.
    """
    event = body.get("event")
    if not isinstance(event, dict):
        return False
    return bool(event.get("bot_id")) or event.get("subtype") in _ECHO_SUBTYPES


# Message subtypes that are still a person writing; joins, topic changes and the like are not.
_PERSON_SUBTYPES = frozenset({None, "", "file_share", "thread_broadcast"})
EVENT_SCOPES = frozenset({"all", "messages", "directMessages", "mentions", "channel"})


def _event_matches(node_data: dict[str, Any], body: dict[str, Any]) -> bool:
    """Whether a Slack Trigger node's `slackEventScope` lets this event start a run.

    `all` (the default, and what older nodes have) starts on every event. The other scopes
    start on a person's message: `messages` anywhere the bot hears, `directMessages` in a
    DM with the bot, `mentions` when the bot is mentioned, `channel` in `slackEventChannel`.
    """
    scope = str(node_data.get("slackEventScope") or "all")
    if scope == "all":
        return True
    event = body.get("event")
    if not isinstance(event, dict):
        return False
    if scope == "mentions":
        return event.get("type") == "app_mention"
    if event.get("type") != "message" or event.get("subtype") not in _PERSON_SUBTYPES:
        return False
    if scope == "directMessages":
        return event.get("channel_type") == "im"
    if scope == "channel":
        wanted = str(node_data.get("slackEventChannel") or "").strip()
        return bool(wanted) and event.get("channel") == wanted
    return scope == "messages"


# event_id of deliveries already handled; Slack redelivers an event it believes timed out.
_SEEN_EVENTS: dict[str, float] = {}
_SEEN_EVENT_TTL_SECONDS = 3600


def _first_delivery(event_id: object) -> bool:
    """False for an event_id handled within the last hour."""
    now = time.time()
    for key, seen_at in list(_SEEN_EVENTS.items()):
        if now - seen_at > _SEEN_EVENT_TTL_SECONDS:
            _SEEN_EVENTS.pop(key, None)
    key = str(event_id or "")
    if not key:
        return True
    if key in _SEEN_EVENTS:
        return False
    _SEEN_EVENTS[key] = now
    return True


async def _listening_triggers(
    db: AsyncSession, credential_id: str
) -> list[tuple[Workflow, str, dict[str, Any]]]:
    """Active Slack Trigger nodes on this credential, in workflows whose owner may use it."""
    try:
        cred_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return []
    result = await db.execute(
        select(Workflow).where(
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps(
                    [{"type": "slackTrigger", "data": {"credentialId": credential_id}}]
                )
            )
        )
    )
    targets: list[tuple[Workflow, str, dict[str, Any]]] = []
    for workflow in result.scalars():
        # Someone else's credential id pasted into a node must not receive that workspace's events.
        if await get_accessible_credential(db, cred_uuid, workflow.owner_id) is None:
            continue
        for node in workflow.nodes or []:
            data = node.get("data") if isinstance(node, dict) else None
            if (
                isinstance(data, dict)
                and node.get("type") == "slackTrigger"
                and data.get("credentialId") == credential_id
                and data.get("active", True) is not False
            ):
                targets.append((workflow, str(node.get("id")), data))
    return targets


async def _is_bot_credential(db: AsyncSession, credential_id: str) -> bool:
    try:
        cred_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return False
    result = await db.execute(select(Credential.type).where(Credential.id == cred_uuid))
    return result.scalar_one_or_none() == CredentialType.slack_bot


async def _get_signing_secret(db: AsyncSession, credential_id: str) -> str | None:
    """Decrypt and return the signing_secret from a slack_trigger or slack_bot credential."""
    try:
        cred_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return None
    result = await db.execute(
        select(Credential).where(
            Credential.id == cred_uuid,
            Credential.type.in_([CredentialType.slack_trigger, CredentialType.slack_bot]),
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
                trigger_source="slack",
                actor_user_id=fresh_workflow.owner_id,
            )
            try:
                result = await dispatch_workflow(
                    workflow_id=fresh_workflow.id,
                    nodes=fresh_workflow.nodes,
                    edges=fresh_workflow.edges,
                    inputs=inputs,
                    workflow_cache=workflow_cache,
                    trigger_source="slack",
                    credentials_owner_id=fresh_workflow.owner_id,
                    execution_id=execution_id,
                    credentials_context=credentials_context,
                    global_variables_context=global_variables_context,
                    trace_user_id=fresh_workflow.owner_id,
                    actor_user_id=fresh_workflow.owner_id,
                    cancel_event=cancel_event,
                )
            finally:
                clear_execution(
                    execution_id, handle=getattr(cancel_event, "_execution_handle", None)
                )

            # An offloaded run's history is written where it ran, or by the
            # dispatcher itself when the queue retired it before it ran.
            if getattr(result, "history_written", False):
                log_offloaded_run(
                    logger, workflow_id=workflow.id, trigger="Slack trigger", result=result
                )
                return

            if needs_local_pending_persist(result):
                history_entry, _ = await persist_pending_execution(
                    db=db,
                    workflow=fresh_workflow,
                    enriched_inputs=inputs,
                    execution_result=result,
                    trigger_source="Slack",
                    credentials_owner_id=fresh_workflow.owner_id,
                    trace_user_id=fresh_workflow.owner_id,
                    public_base_url=build_default_public_base_url(),
                    history_entry_id=execution_id,
                )
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=fresh_workflow.id,
                    owner_id=fresh_workflow.owner_id,
                    workflow_name_snapshot=fresh_workflow.name,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    started_at=getattr(history_entry, "started_at", None),
                )
                await db.commit()
                logger.info("Workflow %s paused for human review via Slack", workflow.id)
                return

            history_entry = ExecutionHistory(
                id=execution_id,
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

    # SECURITY: Slack webhook signature verification must fail closed.
    # See security advisory GHSA-pm6h-x3h5-j38h, finding H1. Previously, a missing
    # credential_id or empty signing_secret caused verification to be skipped
    # entirely, allowing anyone with the webhook URL to trigger the workflow with
    # the owner's credentials.
    #
    # Client-facing error is a single generic message so probing the webhook URL
    # does not reveal which nodes are misconfigured. The specific reason is logged
    # server-side only.
    if not credential_id:
        logger.warning(
            "Slack webhook rejected: no credential_id on trigger node_id=%s",
            node_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid webhook credential configuration",
        )

    async with async_session_maker() as db:
        signing_secret = await _get_signing_secret(db, credential_id)

    if not signing_secret:
        logger.warning(
            "Slack webhook rejected: credential_id=%s has no signing_secret (node_id=%s)",
            credential_id,
            node_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid webhook credential configuration",
        )

    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not _verify_slack_signature(signing_secret, raw_body, timestamp, signature):
        logger.warning("Invalid Slack signature for node_id=%s", node_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Slack signature",
        )

    if _is_bot_echo(body):
        async with async_session_maker() as db:
            if await _is_bot_credential(db, credential_id):
                return {"ok": True}
    if trigger_node and not _event_matches(trigger_node.get("data") or {}, body):
        return {"ok": True}

    # Build safe headers (strip sensitive ones)
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in _SENSITIVE_HEADERS}

    # Fire workflow execution as background task — Slack requires 200 within 3s
    asyncio.create_task(_execute_workflow_background(workflow, node_id, body, safe_headers))

    return {"ok": True}


@router.post("/events/{credential_id}")
async def slack_events(credential_id: str, request: Request) -> dict[str, Any]:
    """Receive a Slack app's events once and start every Slack Trigger that listens to them.

    A Slack app has one Event Subscriptions URL. Pointing it here, at the credential, lets
    any number of workflows on that credential listen, each with its own scope (DMs,
    mentions, one channel). Signatures are checked with the credential's signing secret.
    """
    raw_body = await request.body()
    try:
        body: dict[str, Any] = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    async with async_session_maker() as db:
        signing_secret = await _get_signing_secret(db, credential_id)
    if not signing_secret:
        logger.warning("Slack events rejected: credential %s has no signing secret", credential_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid webhook credential configuration",
        )
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not _verify_slack_signature(signing_secret, raw_body, timestamp, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Slack signature")
    if not _first_delivery(body.get("event_id")):
        return {"ok": True}

    async with async_session_maker() as db:
        if _is_bot_echo(body) and await _is_bot_credential(db, credential_id):
            return {"ok": True}
        targets = await _listening_triggers(db, credential_id)

    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in _SENSITIVE_HEADERS}
    started = 0
    for workflow, node_id, node_data in targets:
        if _event_matches(node_data, body):
            asyncio.create_task(_execute_workflow_background(workflow, node_id, body, safe_headers))
            started += 1
    logger.info("Slack event for credential %s started %d workflow(s)", credential_id, started)
    return {"ok": True}
