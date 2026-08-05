"""Cal.com webhook endpoint for workflow triggers."""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.deps import get_current_user
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
    get_workflow_for_user,
)
from app.db.models import (
    CalWebhookDeliveryReceipt,
    CalWebhookSubscription,
    CredentialType,
    ExecutionHistory,
    User,
    Workflow,
)
from app.db.session import async_session_maker, get_db
from app.models.schemas import CalWebhookSubscriptionResponse
from app.services.cal_api_service import (
    CalApiClient,
    CalApiConfig,
    CalApiError,
    lock_cal_subscription,
)
from app.services.codex_followup_service import (
    is_codex_pending_execution,
    persist_pending_codex_followup_execution,
)
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config, encrypt_config
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
_NO_SHOW_EVENTS = frozenset({"AFTER_HOSTS_CAL_VIDEO_NO_SHOW", "AFTER_GUESTS_CAL_VIDEO_NO_SHOW"})

CAL_WEBHOOK_EVENTS: tuple[str, ...] = (
    "BOOKING_CREATED",
    "BOOKING_PAYMENT_INITIATED",
    "BOOKING_PAID",
    "BOOKING_RESCHEDULED",
    "BOOKING_REQUESTED",
    "BOOKING_CANCELLED",
    "BOOKING_REJECTED",
    "BOOKING_NO_SHOW_UPDATED",
    "BOOKING_LOCATION_UPDATED",
    "FORM_SUBMITTED",
    "MEETING_ENDED",
    "MEETING_STARTED",
    "RECORDING_READY",
    "INSTANT_MEETING",
    "INSTANT_MEETING_ACCEPTED",
    "RECORDING_TRANSCRIPTION_GENERATED",
    "OOO_CREATED",
    "AFTER_HOSTS_CAL_VIDEO_NO_SHOW",
    "AFTER_GUESTS_CAL_VIDEO_NO_SHOW",
    "FORM_SUBMITTED_NO_EVENT",
    "ROUTING_FORM_FALLBACK_HIT",
    "DELEGATION_CREDENTIAL_ERROR",
    "WRONG_ASSIGNMENT_REPORT",
    "DELEGATION_CREDENTIAL_SECRET_ROTATION_FAILED",
    "DELEGATION_CREDENTIAL_ROTATION_REQUIRED",
    "DELEGATION_CREDENTIAL_SECRET_ROTATED",
    "CALENDAR_ENTRY_REJECTED",
)
_FORWARDED_HEADERS: frozenset[str] = frozenset(
    {
        "content-type",
        "user-agent",
        "x-cal-webhook-version",
        "x-request-id",
    }
)


class _ManagedCalWebhookConfig(BaseModel):
    """Validated managed fields read from a saved Cal.com Trigger node."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    setup_mode: Literal["managed"] = Field(alias="setupMode")
    cal_api_credential_id: str = Field(alias="calApiCredentialId", min_length=1)
    events: list[str] = Field(min_length=1)
    payload_version: Literal["2021-10-20", "2026-07-27"] = Field(
        default="2021-10-20",
        alias="payloadVersion",
    )
    payload_template: str = Field(default="", alias="payloadTemplate", max_length=100_000)
    no_show_time: int = Field(default=5, alias="noShowTime", ge=1)
    no_show_time_unit: Literal["MINUTE", "HOUR", "DAY"] = Field(
        default="MINUTE",
        alias="noShowTimeUnit",
    )
    active: bool = Field(default=True, strict=True)

    @field_validator("events", mode="before")
    @classmethod
    def _validate_events_shape(cls, value: object) -> object:
        if not isinstance(value, list) or not all(isinstance(event, str) for event in value):
            raise ValueError("events must be an array of strings")
        return value

    @field_validator("events")
    @classmethod
    def _normalize_events(cls, value: list[str]) -> list[str]:
        events = list(dict.fromkeys(event.strip() for event in value if event.strip()))
        if not events:
            raise ValueError("select at least one Cal.com event")
        invalid_events = sorted(set(events) - set(CAL_WEBHOOK_EVENTS))
        if invalid_events:
            raise ValueError(f"unsupported Cal.com events: {', '.join(invalid_events)}")
        return events


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
                and node.get("data", {}).get("setupMode", "manual") == "manual"
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


async def _get_managed_webhook_secret(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_id: str,
) -> str | None:
    result = await db.execute(
        select(CalWebhookSubscription).where(
            CalWebhookSubscription.workflow_id == workflow_id,
            CalWebhookSubscription.node_id == node_id,
            CalWebhookSubscription.status == "active",
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        return None
    config = decrypt_config(subscription.encrypted_secret)
    secret = str(config.get("webhook_secret") or "").strip()
    return secret or None


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


def _managed_webhook_url(workflow_id: uuid.UUID, node_id: str) -> str:
    public_base_url = build_default_public_base_url()
    return f"{public_base_url}/api/cal/webhook/{workflow_id}/{node_id}"


async def _cal_api_client_for_credential(
    db: AsyncSession,
    credential_id: str,
    owner_id: uuid.UUID,
) -> tuple[uuid.UUID, CalApiClient]:
    try:
        credential_uuid = uuid.UUID(credential_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select a valid Cal.com API credential",
        )
    credential = await get_accessible_credential(db, credential_uuid, owner_id)
    if credential is None or credential.type != CredentialType.cal_api:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select an accessible Cal.com API credential",
        )
    config = decrypt_config(credential.encrypted_config)
    api_key = str(config.get("api_key") or "").strip()
    base_url = str(config.get("base_url") or "https://api.cal.com").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cal.com API credential is missing its API key",
        )
    return credential_uuid, CalApiClient(CalApiConfig(api_key=api_key, base_url=base_url))


def _subscription_response(
    subscription: CalWebhookSubscription,
) -> CalWebhookSubscriptionResponse:
    config = subscription.configuration or {}
    events = config.get("events") if isinstance(config.get("events"), list) else []
    return CalWebhookSubscriptionResponse(
        workflow_id=subscription.workflow_id,
        node_id=subscription.node_id,
        external_webhook_id=subscription.external_webhook_id,
        subscriber_url=subscription.subscriber_url,
        status=subscription.status,
        events=[str(event) for event in events],
        payload_version=str(config.get("payloadVersion") or "2021-10-20"),
        no_show_time=int(config.get("noShowTime") or 5),
        no_show_time_unit=str(config.get("noShowTimeUnit") or "MINUTE"),
        last_error=subscription.last_error,
        synced_at=subscription.synced_at,
    )


def _managed_config_from_node(node_data: object) -> _ManagedCalWebhookConfig:
    """Validate saved node data and expose a stable client-facing validation error."""
    try:
        return _ManagedCalWebhookConfig.model_validate(node_data)
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_error.get("loc", ()))
        message = str(first_error.get("msg") or "Invalid value")
        detail = f"Invalid Cal.com Trigger configuration: {location}: {message}"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


async def _create_or_reconcile_webhook(
    client: CalApiClient,
    body: dict[str, Any],
    subscriber_url: str,
) -> tuple[dict[str, Any], bool]:
    """Create a webhook or adopt the existing webhook for the same subscriber URL."""
    async with client:
        try:
            return await client.create_webhook(body), True
        except CalApiError as exc:
            if exc.status_code != status.HTTP_409_CONFLICT:
                raise
            webhooks = await client.list_webhooks()
            existing = next(
                (
                    webhook
                    for webhook in webhooks
                    if str(webhook.get("subscriberUrl") or "") == subscriber_url
                    and webhook.get("id") is not None
                ),
                None,
            )
            if existing is None:
                raise exc
            webhook_id = str(existing["id"])
            return await client.update_webhook(webhook_id, body), False


async def _compensate_created_webhook(client: CalApiClient, webhook_id: str) -> None:
    """Best-effort removal when a remote create cannot be persisted locally."""
    try:
        await client.delete_webhook(webhook_id)
    except CalApiError as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            logger.exception("Failed to compensate Cal.com webhook creation %s", webhook_id)
    except Exception:
        logger.exception("Failed to compensate Cal.com webhook creation %s", webhook_id)


async def _compensate_updated_webhook(
    client: CalApiClient,
    webhook_id: str,
    previous_body: dict[str, Any],
) -> None:
    """Best-effort restore an existing remote webhook after local persistence fails."""
    try:
        await client.update_webhook(webhook_id, previous_body)
    except Exception:
        logger.exception("Failed to compensate Cal.com webhook update %s", webhook_id)


def _webhook_request_body(
    config: _ManagedCalWebhookConfig,
    *,
    subscriber_url: str,
    webhook_secret: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "active": True,
        "subscriberUrl": subscriber_url,
        "triggers": config.events,
        "secret": webhook_secret,
        "version": config.payload_version,
        # Cal.com PATCH semantics retain an omitted template, so always send this field.
        "payloadTemplate": config.payload_template.strip(),
    }
    if _NO_SHOW_EVENTS.intersection(config.events):
        body["time"] = config.no_show_time
        body["timeUnit"] = config.no_show_time_unit
    return body


def _stored_webhook_request_body(
    subscription: CalWebhookSubscription,
    webhook_secret: str,
) -> dict[str, Any] | None:
    stored = subscription.configuration or {}
    events = stored.get("events")
    if not isinstance(events, list) or not events:
        return None
    node_data = {
        "setupMode": "managed",
        "calApiCredentialId": str(subscription.credential_id or "stored"),
        "events": events,
        "payloadVersion": stored.get("payloadVersion") or "2021-10-20",
        "payloadTemplate": stored.get("payloadTemplate") or "",
        "noShowTime": stored.get("noShowTime") or 5,
        "noShowTimeUnit": stored.get("noShowTimeUnit") or "MINUTE",
        "active": True,
    }
    try:
        stored_config = _ManagedCalWebhookConfig.model_validate(node_data)
    except ValidationError:
        return None
    return _webhook_request_body(
        stored_config,
        subscriber_url=subscription.subscriber_url,
        webhook_secret=webhook_secret,
    )


async def _delete_remote_subscription(
    db: AsyncSession,
    subscription: CalWebhookSubscription,
    owner_id: uuid.UUID,
) -> None:
    if subscription.external_webhook_id:
        if subscription.credential_id is None:
            raise CalApiError("Managed Cal.com webhook has no API credential")
        _credential_id, client = await _cal_api_client_for_credential(
            db,
            str(subscription.credential_id),
            owner_id,
        )
        try:
            await client.delete_webhook(subscription.external_webhook_id)
        except CalApiError as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
    subscription.external_webhook_id = None
    subscription.status = "inactive"
    subscription.last_error = None
    subscription.synced_at = datetime.now(timezone.utc)


@router.get("/events", response_model=list[str])
async def list_cal_webhook_events(
    _current_user: User = Depends(get_current_user),
) -> list[str]:
    """List event names supported by Cal.com managed webhooks."""
    return list(CAL_WEBHOOK_EVENTS)


@router.get(
    "/subscriptions/{workflow_id}/{node_id}",
    response_model=CalWebhookSubscriptionResponse,
)
async def get_cal_webhook_subscription(
    workflow_id: uuid.UUID,
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalWebhookSubscriptionResponse:
    """Return the managed subscription state for one trigger node."""
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    result = await db.execute(
        select(CalWebhookSubscription).where(
            CalWebhookSubscription.workflow_id == workflow_id,
            CalWebhookSubscription.node_id == node_id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Managed Cal.com webhook is not configured",
        )
    return _subscription_response(subscription)


@router.post(
    "/subscriptions/{workflow_id}/{node_id}/sync",
    response_model=CalWebhookSubscriptionResponse,
)
async def sync_cal_webhook_subscription(
    workflow_id: uuid.UUID,
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalWebhookSubscriptionResponse:
    """Create or update a Cal.com API-managed webhook from the saved node configuration."""
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workflow owner can manage Cal.com webhooks",
        )
    trigger_node = next(
        (
            node
            for node in workflow.nodes or []
            if node.get("id") == node_id and node.get("type") == "calTrigger"
        ),
        None,
    )
    if trigger_node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger node not found")
    node_data = trigger_node.get("data", {})
    if not isinstance(node_data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Cal.com Trigger configuration: data must be an object",
        )
    if node_data.get("setupMode", "manual") != "managed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set the Cal.com Trigger setup mode to managed first",
        )
    if node_data.get("active") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enable the Cal.com Trigger before syncing its webhook",
        )
    config = _managed_config_from_node(node_data)

    credential_id, client = await _cal_api_client_for_credential(
        db,
        config.cal_api_credential_id,
        workflow.owner_id,
    )
    await lock_cal_subscription(db, workflow_id, node_id)
    result = await db.execute(
        select(CalWebhookSubscription).where(
            CalWebhookSubscription.workflow_id == workflow_id,
            CalWebhookSubscription.node_id == node_id,
        )
    )
    subscription = result.scalar_one_or_none()
    previous_status = subscription.status if subscription is not None else None
    if subscription is not None and subscription.credential_id != credential_id:
        try:
            await _delete_remote_subscription(db, subscription, workflow.owner_id)
        except (CalApiError, HTTPException) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to remove the previous Cal.com webhook: {exc}",
            )

    subscriber_url = _managed_webhook_url(workflow_id, node_id)
    if subscription is None:
        subscription = CalWebhookSubscription(
            workflow_id=workflow_id,
            node_id=node_id,
            credential_id=credential_id,
            subscriber_url=subscriber_url,
            encrypted_secret=encrypt_config({"webhook_secret": secrets.token_hex(32)}),
            configuration={},
            status="inactive",
        )
        db.add(subscription)
        await db.flush()
    secret_config = decrypt_config(subscription.encrypted_secret)
    webhook_secret = str(secret_config.get("webhook_secret") or "")
    body = _webhook_request_body(
        config,
        subscriber_url=subscriber_url,
        webhook_secret=webhook_secret,
    )
    previous_remote_body = (
        _stored_webhook_request_body(subscription, webhook_secret)
        if subscription.external_webhook_id
        else None
    )
    previous_external_webhook_id = subscription.external_webhook_id
    created_remote = False
    try:
        if subscription.external_webhook_id:
            try:
                webhook = await client.update_webhook(subscription.external_webhook_id, body)
            except CalApiError as exc:
                if exc.status_code != status.HTTP_404_NOT_FOUND:
                    raise
                subscription.external_webhook_id = None
                webhook, created_remote = await _create_or_reconcile_webhook(
                    client,
                    body,
                    subscriber_url,
                )
        else:
            webhook, created_remote = await _create_or_reconcile_webhook(
                client,
                body,
                subscriber_url,
            )
    except CalApiError as exc:
        remote_still_active = bool(subscription.external_webhook_id) and (
            exc.status_code != status.HTTP_404_NOT_FOUND
            and previous_status == "active"
            and subscription.credential_id == credential_id
        )
        subscription.status = "active" if remote_still_active else "error"
        subscription.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    external_id = webhook.get("id")
    if external_id is None:
        subscription.status = "error"
        subscription.last_error = "Cal.com API response did not include a webhook ID"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=subscription.last_error,
        )
    subscription.credential_id = credential_id
    subscription.external_webhook_id = str(external_id)
    subscription.subscriber_url = subscriber_url
    subscription.configuration = {
        "events": config.events,
        "payloadVersion": config.payload_version,
        "payloadTemplate": config.payload_template.strip(),
        "noShowTime": config.no_show_time,
        "noShowTimeUnit": config.no_show_time_unit,
    }
    subscription.status = "active"
    subscription.last_error = None
    subscription.synced_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except Exception as exc:
        try:
            await db.rollback()
        except Exception:
            logger.exception("Failed to roll back Cal.com subscription transaction")
        if created_remote:
            await _compensate_created_webhook(client, str(external_id))
        elif previous_remote_body is not None and previous_external_webhook_id:
            await _compensate_updated_webhook(
                client,
                previous_external_webhook_id,
                previous_remote_body,
            )
        logger.exception("Failed to persist Cal.com webhook subscription")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to persist the Cal.com webhook subscription",
        ) from exc
    return _subscription_response(subscription)


@router.delete(
    "/subscriptions/{workflow_id}/{node_id}",
    response_model=CalWebhookSubscriptionResponse,
)
async def deactivate_cal_webhook_subscription(
    workflow_id: uuid.UUID,
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalWebhookSubscriptionResponse:
    """Delete the remote Cal.com webhook while retaining local status."""
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workflow owner can manage Cal.com webhooks",
        )
    await lock_cal_subscription(db, workflow_id, node_id)
    result = await db.execute(
        select(CalWebhookSubscription).where(
            CalWebhookSubscription.workflow_id == workflow_id,
            CalWebhookSubscription.node_id == node_id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Managed Cal.com webhook is not configured",
        )
    previous_status = subscription.status
    previous_external_webhook_id = subscription.external_webhook_id
    try:
        await _delete_remote_subscription(db, subscription, workflow.owner_id)
    except (CalApiError, HTTPException) as exc:
        remote_may_still_be_active = bool(previous_external_webhook_id) and (
            previous_status == "active"
        )
        subscription.status = "active" if remote_may_still_be_active else "error"
        subscription.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    await db.commit()
    return _subscription_response(subscription)


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
        setup_mode = str(node_data.get("setupMode") or "manual")
        credential_id = str(node_data.get("credentialId") or "").strip()
        if setup_mode == "managed":
            webhook_secret = await _get_managed_webhook_secret(db, workflow.id, node_id)
        else:
            webhook_secret = await _get_webhook_secret(db, credential_id, workflow.owner_id)
        if not webhook_secret:
            logger.warning(
                "Cal.com webhook rejected: invalid %s configuration on node_id=%s",
                setup_mode,
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
    """Keep pre-managed manual webhook URLs working during migration."""
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
