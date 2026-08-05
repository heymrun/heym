"""Cal.com webhook endpoint for workflow triggers."""

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import (
    CalWebhookDeliveryReceipt,
    CredentialType,
    ExecutionHistory,
    Workflow,
)
from app.db.session import async_session_maker
from app.services.codex_followup_service import (
    is_codex_pending_execution,
    persist_pending_codex_followup_execution,
)
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.execution_cancellation import (
    clear_execution,
    persist_registered_execution,
    register_execution,
)
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_default_public_base_url, persist_pending_hitl_execution
from app.services.workflow_executor import (
    WorkflowCancelledError,
    WorkflowTimeoutError,
    _to_json_compatible,
    execute_workflow,
)

logger = logging.getLogger("cal_webhook")

router = APIRouter()

_TRIGGER_SOURCE = "Cal.com"
_DEDUPLICATION_WINDOW = timedelta(hours=24)
_RECEIPT_CLEANUP_INTERVAL_SECONDS = 60 * 60
_BACKGROUND_SHUTDOWN_TIMEOUT_SECONDS = 30.0
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()
_BACKGROUND_CANCEL_EVENTS: dict[asyncio.Task[None], Event] = {}
_LAST_RECEIPT_CLEANUP_AT = float("-inf")
_FORWARDED_HEADERS: frozenset[str] = frozenset(
    {
        "content-type",
        "user-agent",
        "x-cal-webhook-version",
        "x-request-id",
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


def _build_trigger_inputs(
    node_id: str,
    event_body: dict[str, Any],
    safe_headers: dict[str, str],
) -> dict[str, Any]:
    """Normalize wrapped and flat Cal.com webhook events for node execution."""
    payload = event_body["payload"] if "payload" in event_body else event_body
    return {
        "triggered_by": _TRIGGER_SOURCE,
        "trigger_node_id": node_id,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "event": event_body,
        "trigger_event": event_body.get("triggerEvent"),
        "payload": payload,
        "headers": safe_headers,
    }


def _deduplication_key(
    node_id: str,
    event_body: dict[str, Any],
) -> str | None:
    """Return a digest only when the payload carries a stable delivery identity."""
    idempotency_key = event_body.get("idempotencyKey")
    created_at = event_body.get("createdAt")
    if idempotency_key:
        identity = f"idempotencyKey:{idempotency_key}"
    elif created_at:
        canonical_body = json.dumps(
            event_body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        identity = f"createdAt:{created_at}\0{canonical_body}"
    else:
        return None
    digest = hashlib.sha256()
    digest.update(node_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(identity.encode("utf-8"))
    return digest.hexdigest()


async def _find_workflow_trigger(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_id: str,
) -> tuple[Workflow, dict[str, Any]] | None:
    """Find one active workflow and its requested Cal.com Trigger node."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.scheduled_for_deletion.is_(None),
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        return None
    trigger_node = next(
        (
            node
            for node in workflow.nodes
            if node.get("id") == node_id
            and node.get("type") == "calTrigger"
            and node.get("data", {}).get("active") is not False
        ),
        None,
    )
    if trigger_node is None:
        return None
    return workflow, trigger_node


async def _resolve_legacy_workflow_id(
    db: AsyncSession,
    node_id: str,
    raw_body: bytes,
    signature: str,
) -> uuid.UUID | None:
    """Resolve an old node-only URL only when its HMAC identifies one workflow."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.scheduled_for_deletion.is_(None),
            text("nodes::jsonb @> (:node_filter)::jsonb").bindparams(
                node_filter=json.dumps([{"id": node_id, "type": "calTrigger"}])
            ),
        )
    )
    candidates_found = False
    matching_workflow_ids: list[uuid.UUID] = []
    for workflow in result.scalars().all():
        trigger_node = next(
            (
                node
                for node in workflow.nodes or []
                if node.get("id") == node_id
                and node.get("type") == "calTrigger"
                and node.get("data", {}).get("active") is not False
            ),
            None,
        )
        if trigger_node is None:
            continue
        candidates_found = True
        credential_id = str(trigger_node.get("data", {}).get("credentialId") or "").strip()
        webhook_secret = await _get_webhook_secret(db, credential_id, workflow.owner_id)
        if webhook_secret and _verify_cal_signature(webhook_secret, raw_body, signature):
            matching_workflow_ids.append(workflow.id)

    if len(matching_workflow_ids) == 1:
        return matching_workflow_ids[0]
    if len(matching_workflow_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Legacy Cal.com webhook URL matches multiple workflows; update the subscriber URL",
        )
    if candidates_found:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Cal.com signature",
        )
    return None


async def _get_webhook_secret(
    db: AsyncSession,
    credential_id: str,
    owner_id: uuid.UUID,
) -> str | None:
    """Return an accessible Cal.com Trigger credential's webhook secret."""
    try:
        credential_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        return None
    credential = await get_accessible_credential(db, credential_uuid, owner_id)
    if credential is None or credential.type != CredentialType.cal_trigger:
        return None
    config = decrypt_config(credential.encrypted_config)
    webhook_secret = str(config.get("webhook_secret") or "").strip()
    return webhook_secret or None


async def _reserve_execution(
    db: AsyncSession,
    workflow: Workflow,
    inputs: dict[str, Any],
    deduplication_key: str | None,
) -> tuple[uuid.UUID, Event] | None:
    """Atomically reserve a durable execution unless this delivery already exists."""
    execution_id = uuid.uuid4()
    if deduplication_key is not None:
        received_at = datetime.now(timezone.utc)
        await db.execute(
            delete(CalWebhookDeliveryReceipt).where(
                CalWebhookDeliveryReceipt.workflow_id == workflow.id,
                CalWebhookDeliveryReceipt.node_id == inputs["trigger_node_id"],
                CalWebhookDeliveryReceipt.deduplication_key == deduplication_key,
                CalWebhookDeliveryReceipt.received_at < received_at - _DEDUPLICATION_WINDOW,
            )
        )
        receipt_statement = (
            pg_insert(CalWebhookDeliveryReceipt)
            .values(
                id=uuid.uuid4(),
                workflow_id=workflow.id,
                node_id=inputs["trigger_node_id"],
                deduplication_key=deduplication_key,
                execution_id=execution_id,
                received_at=received_at,
            )
            .on_conflict_do_nothing(constraint="uq_cal_webhook_delivery_receipt")
            .returning(CalWebhookDeliveryReceipt.execution_id)
        )
        inserted_execution_id = (await db.execute(receipt_statement)).scalar_one_or_none()
        if inserted_execution_id is None:
            return None

    await db.execute(
        pg_insert(ExecutionHistory).values(
            id=execution_id,
            workflow_id=workflow.id,
            inputs=inputs,
            outputs={},
            node_results=[],
            status="running",
            execution_time_ms=0.0,
            trigger_source=_TRIGGER_SOURCE,
        )
    )

    cancel_event = register_execution(
        workflow_id=workflow.id,
        execution_id=execution_id,
        inputs=inputs,
        trigger_source=_TRIGGER_SOURCE,
        actor_user_id=workflow.owner_id,
    )
    try:
        await persist_registered_execution(db, execution_id)
        await db.commit()
    except Exception:
        clear_execution(execution_id)
        await db.rollback()
        raise
    return execution_id, cancel_event


async def _persist_terminal_execution(
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
    inputs: dict[str, Any],
    execution_started_at: float,
    *,
    terminal_status: str,
    error_message: str | None = None,
) -> bool:
    """Persist a terminal execution and its analytics snapshot."""
    execution_time_ms = (time.monotonic() - execution_started_at) * 1000
    outputs = {"error": error_message} if error_message else {}
    async with async_session_maker() as db:
        workflow = await db.get(Workflow, workflow_id)
        await db.execute(
            pg_insert(ExecutionHistory)
            .values(
                id=execution_id,
                workflow_id=workflow_id,
                inputs=inputs,
                outputs=outputs,
                node_results=[],
                status=terminal_status,
                execution_time_ms=execution_time_ms,
                trigger_source=_TRIGGER_SOURCE,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "outputs": outputs,
                    "node_results": [],
                    "status": terminal_status,
                    "execution_time_ms": execution_time_ms,
                },
            )
        )
        if workflow is not None:
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=terminal_status,
                execution_time_ms=execution_time_ms,
            )
        await db.commit()
    return True


async def _cleanup_expired_delivery_receipts() -> None:
    """Remove expired receipts outside the webhook reservation transaction."""
    try:
        async with async_session_maker() as db:
            await db.execute(
                delete(CalWebhookDeliveryReceipt).where(
                    CalWebhookDeliveryReceipt.received_at
                    < datetime.now(timezone.utc) - _DEDUPLICATION_WINDOW
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to clean up expired Cal.com delivery receipts")


def _schedule_receipt_cleanup() -> None:
    """Rate-limit global receipt cleanup to once per process per hour."""
    global _LAST_RECEIPT_CLEANUP_AT

    now = time.monotonic()
    if now - _LAST_RECEIPT_CLEANUP_AT < _RECEIPT_CLEANUP_INTERVAL_SECONDS:
        return
    _LAST_RECEIPT_CLEANUP_AT = now
    task = asyncio.create_task(_cleanup_expired_delivery_receipts())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_discard_background_task)


async def _execute_workflow_background(
    workflow_id: uuid.UUID,
    node_id: str,
    inputs: dict[str, Any],
    execution_id: uuid.UUID,
    cancel_event: Event,
) -> None:
    """Execute one reserved Cal.com delivery without blocking the API event loop."""
    logger.info("Executing workflow %s via Cal.com trigger node %s", workflow_id, node_id)
    execution_started_at = time.monotonic()
    try:
        async with async_session_maker() as db:
            trigger_match = await _find_workflow_trigger(db, workflow_id, node_id)
            if trigger_match is None:
                raise RuntimeError("Cal.com trigger workflow or node is no longer active")
            fresh_workflow, _trigger_node = trigger_match
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

        execution_task = asyncio.create_task(
            asyncio.to_thread(
                execute_workflow,
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
                timeout_seconds=fresh_workflow.workflow_timeout_seconds,
                workflow_name=fresh_workflow.name,
                workflow_description=fresh_workflow.description or "",
                execution_id=str(execution_id),
                public_base_url=build_default_public_base_url(),
            )
        )
        try:
            result = await asyncio.shield(execution_task)
        except asyncio.CancelledError:
            cancel_event.set()
            logger.warning(
                "Waiting for cancelled Cal.com execution %s worker thread to stop",
                execution_id,
            )
            result = await execution_task

        if result.allow_downstream_pending:
            result.join_allow_downstream()

        async with async_session_maker() as db:
            if result.status == "pending":
                history_entry = await db.get(ExecutionHistory, execution_id)
                if history_entry is None:
                    raise RuntimeError("Reserved Cal.com execution history is missing")
                persist_pending = (
                    persist_pending_codex_followup_execution
                    if is_codex_pending_execution(result)
                    else persist_pending_hitl_execution
                )
                await persist_pending(
                    db=db,
                    workflow=fresh_workflow,
                    enriched_inputs=inputs,
                    execution_result=result,
                    trigger_source=_TRIGGER_SOURCE,
                    credentials_owner_id=fresh_workflow.owner_id,
                    trace_user_id=fresh_workflow.owner_id,
                    public_base_url=build_default_public_base_url(),
                    history_entry=history_entry,
                )
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=fresh_workflow.id,
                    owner_id=fresh_workflow.owner_id,
                    workflow_name_snapshot=fresh_workflow.name,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                )
                await db.commit()
                clear_execution(execution_id)
                logger.info("Cal.com execution %s is pending human input", execution_id)
                return

            await db.execute(
                pg_insert(ExecutionHistory)
                .values(
                    id=execution_id,
                    workflow_id=fresh_workflow.id,
                    inputs=inputs,
                    outputs=_to_json_compatible(result.outputs),
                    node_results=_to_json_compatible(result.node_results),
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source=_TRIGGER_SOURCE,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "outputs": _to_json_compatible(result.outputs),
                        "node_results": _to_json_compatible(result.node_results),
                        "status": result.status,
                        "execution_time_ms": result.execution_time_ms,
                    },
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
                        inputs=_to_json_compatible(sub_execution.inputs),
                        outputs=_to_json_compatible(sub_execution.outputs),
                        node_results=_to_json_compatible(sub_execution.node_results),
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
                _to_json_compatible(result.node_results),
                result.sub_workflow_executions,
            )
            await db.commit()

        clear_execution(execution_id)
        logger.info(
            "Workflow %s executed via Cal.com trigger, status: %s",
            workflow_id,
            result.status,
        )
    except WorkflowTimeoutError:
        logger.warning("Cal.com execution %s timed out", execution_id)
        terminal_status = "error"
        error_message = "Cal.com trigger execution timed out"
    except WorkflowCancelledError:
        logger.info("Cal.com execution %s was cancelled", execution_id)
        terminal_status = "cancelled"
        error_message = None
    except Exception:
        logger.exception(
            "Failed to execute workflow %s via Cal.com trigger node %s",
            workflow_id,
            node_id,
        )
        terminal_status = "error"
        error_message = "Cal.com trigger execution failed"
    else:
        return

    try:
        terminal_persisted = await _persist_terminal_execution(
            workflow_id,
            execution_id,
            inputs,
            execution_started_at,
            terminal_status=terminal_status,
            error_message=error_message,
        )
    except Exception:
        logger.exception("Failed to persist terminal Cal.com execution %s", execution_id)
        terminal_persisted = False
    if terminal_persisted:
        clear_execution(execution_id)


def _schedule_execution(
    workflow_id: uuid.UUID,
    node_id: str,
    inputs: dict[str, Any],
    execution_id: uuid.UUID,
    cancel_event: Event,
) -> None:
    """Keep a strong reference to the background task until it completes."""
    task = asyncio.create_task(
        _execute_workflow_background(
            workflow_id,
            node_id,
            inputs,
            execution_id,
            cancel_event,
        )
    )
    _BACKGROUND_TASKS.add(task)
    _BACKGROUND_CANCEL_EVENTS[task] = cancel_event
    task.add_done_callback(_discard_background_task)


def _discard_background_task(task: asyncio.Task[None]) -> None:
    """Drop all strong references after one Cal.com execution finishes."""
    _BACKGROUND_TASKS.discard(task)
    _BACKGROUND_CANCEL_EVENTS.pop(task, None)


async def shutdown_background_tasks() -> None:
    """Cooperatively stop accepted executions without blocking shutdown forever."""
    tasks = list(_BACKGROUND_TASKS)
    if not tasks:
        return
    logger.info("Stopping %d Cal.com background execution(s)", len(tasks))
    for task in tasks:
        cancel_event = _BACKGROUND_CANCEL_EVENTS.get(task)
        if cancel_event is not None:
            cancel_event.set()
    done, pending = await asyncio.wait(
        tasks,
        timeout=_BACKGROUND_SHUTDOWN_TIMEOUT_SECONDS,
    )
    if done:
        await asyncio.gather(*done, return_exceptions=True)
    if pending:
        logger.warning(
            "Timed out waiting for %d Cal.com background execution(s) to stop",
            len(pending),
        )


async def _handle_cal_webhook(
    workflow_id: uuid.UUID,
    node_id: str,
    request: Request,
) -> dict[str, bool]:
    """Verify, deduplicate, and schedule one Cal.com webhook delivery."""
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    async with async_session_maker() as db:
        trigger_match = await _find_workflow_trigger(db, workflow_id, node_id)
        if trigger_match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No workflow found for this webhook URL",
            )
        workflow, trigger_node = trigger_match

        node_data = trigger_node.get("data", {})
        credential_id = str(node_data.get("credentialId") or "").strip()
        webhook_secret = await _get_webhook_secret(db, credential_id, workflow.owner_id)
        if not webhook_secret:
            logger.warning(
                "Cal.com webhook rejected: invalid credential configuration on node_id=%s",
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
            key.lower(): value
            for key, value in request.headers.items()
            if key.lower() in _FORWARDED_HEADERS
        }
        inputs = _build_trigger_inputs(node_id, body, safe_headers)
        reservation = await _reserve_execution(
            db,
            workflow,
            inputs,
            _deduplication_key(node_id, body),
        )

    _schedule_receipt_cleanup()
    if reservation is None:
        logger.info("Ignoring duplicate Cal.com webhook for node_id=%s", node_id)
        return {"ok": True}

    execution_id, cancel_event = reservation
    _schedule_execution(workflow.id, node_id, inputs, execution_id, cancel_event)
    return {"ok": True}


@router.post("/webhook/{workflow_id}/{node_id}")
async def cal_webhook(
    workflow_id: uuid.UUID,
    node_id: str,
    request: Request,
) -> dict[str, bool]:
    """Handle the workflow-specific Cal.com webhook URL."""
    return await _handle_cal_webhook(workflow_id, node_id, request)


@router.post("/webhook/{node_id}", deprecated=True)
async def legacy_cal_webhook(node_id: str, request: Request) -> dict[str, bool]:
    """Keep older node-only webhook URLs working during migration."""
    raw_body = await request.body()
    signature = request.headers.get("x-cal-signature-256", "")
    async with async_session_maker() as db:
        workflow_id = await _resolve_legacy_workflow_id(db, node_id, raw_body, signature)
    if workflow_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workflow found for this webhook URL",
        )
    return await _handle_cal_webhook(workflow_id, node_id, request)
