"""Alerts API - CRUD, backtesting, firing history, AI drafting, and sharing.

Metric computation is not here: it lives in ``app/services/alerts/types/``
behind ``app/services/alerts/registry.py``. This module owns HTTP concerns and
access control only.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import get_accessible_workflow_ids
from app.api.deps import get_current_user
from app.db.models import Alert, AlertEvent, AlertShare, AlertTeamShare, Team, User, Workflow
from app.db.session import get_db
from app.models.alert_schemas import (
    ALERT_TYPE_LABELS,
    AlertCreate,
    AlertDraftRequest,
    AlertDraftResponse,
    AlertEventListResponse,
    AlertEventResponse,
    AlertListResponse,
    AlertPreviewRequest,
    AlertPreviewResponse,
    AlertResponse,
    AlertShareEntry,
    AlertShareRequest,
    AlertTeamShareEntry,
    AlertTeamShareRequest,
    AlertUpdate,
    describe_condition,
    parse_alert_config,
)
from app.services.alert_access import (
    accessible_alerts_filter,
    get_accessible_alert,
    get_owned_alert,
)
from app.services.alerts.context import AlertEvaluationContext, AlertObservation
from app.services.alerts.evaluator import observe
from app.services.alerts.registry import get_alert_handler
from app.services.llm_trace import LLMTraceContext, record_llm_trace

router = APIRouter()

MAX_BACKTEST_STEPS = 200


async def _unacknowledged_counts(
    db: AsyncSession, alert_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Unacknowledged firings per alert, in one grouped query rather than N."""
    if not alert_ids:
        return {}
    result = await db.execute(
        select(AlertEvent.alert_id, func.count())
        .where(AlertEvent.alert_id.in_(alert_ids), AlertEvent.acknowledged_at.is_(None))
        .group_by(AlertEvent.alert_id)
    )
    return {row[0]: int(row[1]) for row in result.all()}


def _to_response(
    alert: Alert,
    *,
    current_user_id: uuid.UUID,
    workflow_name: str | None = None,
    notify_workflow_name: str | None = None,
    unacknowledged_count: int = 0,
) -> AlertResponse:
    """The single place an AlertResponse is built. Do not construct one inline."""
    return AlertResponse(
        id=alert.id,
        owner_id=alert.owner_id,
        name=alert.name,
        description=alert.description,
        alert_type=alert.alert_type,
        scope=alert.scope,
        workflow_id=alert.workflow_id,
        workflow_name=workflow_name,
        config=alert.config,
        condition_summary=describe_condition(alert.alert_type, alert.config),
        enabled=alert.enabled,
        notify_workflow_id=alert.notify_workflow_id,
        notify_workflow_name=notify_workflow_name,
        state=alert.state,
        renotify_mode=alert.renotify_mode,
        cooldown_minutes=alert.cooldown_minutes,
        check_interval_seconds=alert.check_interval_seconds,
        last_evaluated_at=alert.last_evaluated_at,
        last_triggered_at=alert.last_triggered_at,
        last_observed_value=alert.last_observed_value,
        unacknowledged_count=unacknowledged_count,
        is_owner=alert.owner_id == current_user_id,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


async def _assert_workflow_access(
    db: AsyncSession, workflow_id: uuid.UUID | None, user_id: uuid.UUID
) -> None:
    if workflow_id is None:
        return
    accessible = await get_accessible_workflow_ids(db, user_id)
    if workflow_id not in accessible:
        raise HTTPException(status_code=404, detail="Workflow not found")


async def _create_notify_workflow(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    alert_name: str,
    alert_type: str,
) -> uuid.UUID:
    """Create the workflow an alert will run when it fires.

    Seeded with one generic input node rather than an empty canvas, so there is
    something to attach a Slack or email node to. The field is deliberately not
    the alert payload's keys: a run can carry one firing or a batch of them, and
    a node that declares one event's shape would be wrong for an array. The whole
    body is reachable as ``$alert.body`` either way.
    """
    workflow = Workflow(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name=f"{alert_name} notification"[:255],
        description=(
            f"Runs when the {ALERT_TYPE_LABELS.get(alert_type, alert_type)} alert "
            f'"{alert_name}" fires. The alert payload arrives as the input body.'
        ),
        nodes=[
            {
                "id": f"node_{uuid.uuid4().hex[:8]}",
                "type": "textInput",
                "position": {"x": 100, "y": 100},
                "data": {"label": "alert", "value": "", "inputFields": [{"key": "text"}]},
            }
        ],
        edges=[],
    )
    db.add(workflow)
    await db.flush()
    return workflow.id


async def _workflow_names(db: AsyncSession, workflow_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = [wid for wid in workflow_ids if wid is not None]
    if not ids:
        return {}
    result = await db.execute(select(Workflow.id, Workflow.name).where(Workflow.id.in_(ids)))
    return {row[0]: row[1] for row in result.all()}


async def observe_config(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    alert_type: str,
    scope: str,
    workflow_id: uuid.UUID | None,
    config: dict[str, Any],
    window_end: datetime,
) -> AlertObservation:
    """Evaluate a condition that has no persisted Alert row yet.

    This is what makes the wizard's Review step able to backtest before saving.
    """
    parsed = parse_alert_config(alert_type, config)
    window_start = window_end - timedelta(minutes=parsed.window_minutes)

    if scope == "workflow":
        workflow_ids = [workflow_id] if workflow_id else []
    else:
        workflow_ids = await get_accessible_workflow_ids(db, owner_id)

    ctx = AlertEvaluationContext(
        db=db,
        owner_id=owner_id,
        workflow_ids=workflow_ids,
        window_start=window_start,
        window_end=window_end,
        config=parsed,
    )
    handler = get_alert_handler(alert_type)
    return await handler(ctx)


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    enabled: bool | None = None,
    alert_type: str | None = None,
    workflow_id: uuid.UUID | None = None,
    state: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertListResponse:
    filters = [accessible_alerts_filter(current_user.id)]
    if enabled is not None:
        filters.append(Alert.enabled.is_(enabled))
    if alert_type is not None:
        filters.append(Alert.alert_type == alert_type)
    if workflow_id is not None:
        filters.append(Alert.workflow_id == workflow_id)
    if state is not None:
        filters.append(Alert.state == state)

    total_result = await db.execute(select(func.count()).select_from(Alert).where(*filters))
    total = int(total_result.scalar() or 0)

    result = await db.execute(
        select(Alert).where(*filters).order_by(Alert.created_at.desc()).limit(limit).offset(offset)
    )
    alerts = list(result.scalars().all())

    names = await _workflow_names(
        db, [a.workflow_id for a in alerts] + [a.notify_workflow_id for a in alerts]
    )
    unacknowledged = await _unacknowledged_counts(db, [a.id for a in alerts])
    return AlertListResponse(
        items=[
            _to_response(
                a,
                current_user_id=current_user.id,
                workflow_name=names.get(a.workflow_id) if a.workflow_id else None,
                notify_workflow_name=(
                    names.get(a.notify_workflow_id) if a.notify_workflow_id else None
                ),
                unacknowledged_count=unacknowledged.get(a.id, 0),
            )
            for a in alerts
        ],
        total=total,
    )


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    payload: AlertCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertResponse:
    await _assert_workflow_access(db, payload.workflow_id, current_user.id)
    await _assert_workflow_access(db, payload.notify_workflow_id, current_user.id)

    notify_workflow_id = payload.notify_workflow_id
    if notify_workflow_id is None and payload.create_notify_workflow:
        notify_workflow_id = await _create_notify_workflow(
            db, owner_id=current_user.id, alert_name=payload.name, alert_type=payload.alert_type
        )

    alert = Alert(
        # Assigned here rather than left to the flush-time column default so the
        # response can be built without depending on a refresh round trip.
        id=uuid.uuid4(),
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
        alert_type=payload.alert_type,
        scope=payload.scope,
        workflow_id=payload.workflow_id,
        config=payload.config,
        enabled=payload.enabled,
        notify_workflow_id=notify_workflow_id,
        renotify_mode=payload.renotify_mode,
        cooldown_minutes=payload.cooldown_minutes,
        check_interval_seconds=payload.check_interval_seconds,
        state="ok",
        next_check_at=datetime.now(timezone.utc),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    names = await _workflow_names(db, [alert.workflow_id, alert.notify_workflow_id])
    return _to_response(
        alert,
        current_user_id=current_user.id,
        workflow_name=names.get(alert.workflow_id) if alert.workflow_id else None,
        notify_workflow_name=(
            names.get(alert.notify_workflow_id) if alert.notify_workflow_id else None
        ),
    )


@router.get("/events", response_model=AlertEventListResponse)
async def list_all_alert_events(
    unacknowledged: bool = False,
    time_range: str = Query(default="7d", pattern="^(24h|7d|30d|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertEventListResponse:
    """Firings across every alert the user can read. Powers the nav badge."""
    filters: list[Any] = [accessible_alerts_filter(current_user.id)]
    since = _time_range_start(time_range)
    if since is not None:
        filters.append(AlertEvent.triggered_at >= since)
    if unacknowledged:
        filters.append(AlertEvent.acknowledged_at.is_(None))

    base = select(AlertEvent, Alert.name, Alert.alert_type).join(
        Alert, Alert.id == AlertEvent.alert_id
    )

    total_result = await db.execute(
        select(func.count())
        .select_from(AlertEvent)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .where(*filters)
    )
    total = int(total_result.scalar() or 0)

    unack_result = await db.execute(
        select(func.count())
        .select_from(AlertEvent)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .where(accessible_alerts_filter(current_user.id), AlertEvent.acknowledged_at.is_(None))
    )
    unacknowledged_count = int(unack_result.scalar() or 0)

    result = await db.execute(
        base.where(*filters).order_by(AlertEvent.triggered_at.desc()).limit(limit).offset(offset)
    )
    return AlertEventListResponse(
        items=[_event_to_response(row[0], row[1], row[2]) for row in result.all()],
        total=total,
        unacknowledged=unacknowledged_count,
    )


@router.post("/events/{event_id}/acknowledge", response_model=AlertEventResponse)
async def acknowledge_alert_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertEventResponse:
    result = await db.execute(
        select(AlertEvent, Alert.name, Alert.alert_type)
        .join(Alert, Alert.id == AlertEvent.alert_id)
        .where(AlertEvent.id == event_id, accessible_alerts_filter(current_user.id))
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert event not found")

    event = row[0]
    event.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(event)
    return _event_to_response(event, row[1], row[2])


@router.post("/preview", response_model=AlertPreviewResponse)
async def preview_alert(
    payload: AlertPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertPreviewResponse:
    """Backtest an unsaved condition. Writes nothing.

    A user who sets a threshold of 5 and sees "would have fired 400 times" fixes
    the threshold before saving instead of after being paged.
    """
    await _assert_workflow_access(db, payload.workflow_id, current_user.id)
    config = parse_alert_config(payload.alert_type, payload.config)
    now = datetime.now(timezone.utc)

    current = await observe_config(
        db,
        owner_id=current_user.id,
        alert_type=payload.alert_type,
        scope=payload.scope,
        workflow_id=payload.workflow_id,
        config=payload.config,
        window_end=now,
    )

    # Walk the lookback in window-sized steps. Cap the step count so a 1-minute
    # window over 168 hours cannot issue 10,080 queries.
    total_minutes = payload.lookback_hours * 60
    step_minutes = max(config.window_minutes, total_minutes // MAX_BACKTEST_STEPS or 1)
    steps = max(1, min(MAX_BACKTEST_STEPS, total_minutes // step_minutes))

    fire_count = 0
    max_observed = float(current.observed_value or 0.0)
    for index in range(steps):
        step_end = now - timedelta(minutes=step_minutes * index)
        observation = await observe_config(
            db,
            owner_id=current_user.id,
            alert_type=payload.alert_type,
            scope=payload.scope,
            workflow_id=payload.workflow_id,
            config=payload.config,
            window_end=step_end,
        )
        if observation.observed_value is not None:
            max_observed = max(max_observed, float(observation.observed_value))
        if observation.breached:
            fire_count += 1

    return AlertPreviewResponse(
        observed_value=float(current.observed_value or 0.0),
        threshold_value=float(current.threshold_value),
        would_fire_now=current.breached,
        window_start=now - timedelta(minutes=config.window_minutes),
        window_end=now,
        context=current.context,
        backtest_fire_count=fire_count,
        backtest_max_observed=max_observed,
        lookback_hours=payload.lookback_hours,
    )


@router.post("/ai-draft", response_model=AlertDraftResponse)
async def draft_alert_from_prompt(
    payload: AlertDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertDraftResponse:
    # Imported here rather than at module scope: ai_assistant imports heavily and
    # a top-level import creates a cycle through the chat tooling.
    from app.api.ai_assistant import get_openai_client
    from app.services.alerts.ai_draft import build_draft_system_prompt, parse_draft_response
    from app.services.credential_access import get_accessible_credential
    from app.services.encryption import decrypt_config

    credential = await get_accessible_credential(db, payload.credential_id, current_user.id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    accessible_ids = await get_accessible_workflow_ids(db, current_user.id)
    names = await _workflow_names(db, list(accessible_ids))
    workflows = [(wid, names.get(wid, "")) for wid in accessible_ids if wid in names]

    config = decrypt_config(credential.encrypted_config)
    client, provider = get_openai_client(credential.type, config)

    messages = [
        {"role": "system", "content": build_draft_system_prompt(workflows)},
        {"role": "user", "content": payload.prompt},
    ]
    trace_context = LLMTraceContext(
        user_id=current_user.id,
        credential_id=payload.credential_id,
        source="alert_builder",
        node_label="Alert Builder",
    )
    started = time.time()

    try:
        # get_openai_client returns the *synchronous* OpenAI client, so this has to
        # go off the event loop the same way ai_assistant does it. Awaiting the call
        # directly raises TypeError and surfaces as a 502.
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=payload.model,
            messages=messages,
        )
        text = completion.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001
        record_llm_trace(
            context=trace_context,
            request_type="chat.completions",
            request={"model": payload.model, "messages": messages},
            response=None,
            model=payload.model,
            provider=provider,
            error=str(exc),
            elapsed_ms=round((time.time() - started) * 1000, 2),
        )
        raise HTTPException(status_code=502, detail=f"AI draft failed: {exc}") from exc

    usage = getattr(completion, "usage", None)
    record_llm_trace(
        context=trace_context,
        request_type="chat.completions",
        request={"model": payload.model, "messages": messages},
        response={"text": text, "model": payload.model},
        model=payload.model,
        provider=provider,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        elapsed_ms=round((time.time() - started) * 1000, 2),
    )

    draft, clarification = parse_draft_response(text)

    # The model must never hand back an id the user cannot access. Dropping the id
    # keeps the rest of the draft: the wizard opens on Scope so the user picks the
    # workflow themselves, which beats discarding a condition it got right.
    if draft is not None:
        if draft.workflow_id is not None and draft.workflow_id not in accessible_ids:
            draft.workflow_id = None
            if draft.scope == "workflow":
                clarification = "Which workflow should this alert watch?"
        if draft.notify_workflow_id is not None and draft.notify_workflow_id not in accessible_ids:
            draft.notify_workflow_id = None

    return AlertDraftResponse(draft=draft, clarification=clarification)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertResponse:
    alert = await get_accessible_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    names = await _workflow_names(db, [alert.workflow_id, alert.notify_workflow_id])
    unacknowledged = await _unacknowledged_counts(db, [alert.id])
    return _to_response(
        alert,
        current_user_id=current_user.id,
        workflow_name=names.get(alert.workflow_id) if alert.workflow_id else None,
        notify_workflow_name=(
            names.get(alert.notify_workflow_id) if alert.notify_workflow_id else None
        ),
        unacknowledged_count=unacknowledged.get(alert.id, 0),
    )


@router.patch("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: uuid.UUID,
    payload: AlertUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertResponse:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    changes = payload.model_dump(exclude_unset=True)

    # Re-validate the MERGED result, so a partial update cannot produce an
    # invalid combination (e.g. switching to cooldown without cooldown_minutes).
    merged = {
        "name": alert.name,
        "description": alert.description,
        "alert_type": alert.alert_type,
        "scope": alert.scope,
        "workflow_id": alert.workflow_id,
        "config": alert.config,
        "enabled": alert.enabled,
        "notify_workflow_id": alert.notify_workflow_id,
        "renotify_mode": alert.renotify_mode,
        "cooldown_minutes": alert.cooldown_minutes,
        "check_interval_seconds": alert.check_interval_seconds,
    }
    merged.update(changes)
    try:
        validated = AlertCreate(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if "workflow_id" in changes:
        await _assert_workflow_access(db, validated.workflow_id, current_user.id)
    if "notify_workflow_id" in changes:
        await _assert_workflow_access(db, validated.notify_workflow_id, current_user.id)

    notify_workflow_id = validated.notify_workflow_id
    if notify_workflow_id is None and validated.create_notify_workflow:
        notify_workflow_id = await _create_notify_workflow(
            db,
            owner_id=current_user.id,
            alert_name=validated.name,
            alert_type=validated.alert_type,
        )

    was_enabled = alert.enabled
    alert.name = validated.name
    alert.description = validated.description
    alert.scope = validated.scope
    alert.workflow_id = validated.workflow_id
    alert.config = validated.config
    alert.enabled = validated.enabled
    alert.notify_workflow_id = notify_workflow_id
    alert.renotify_mode = validated.renotify_mode
    alert.cooldown_minutes = validated.cooldown_minutes
    alert.check_interval_seconds = validated.check_interval_seconds

    # A re-enabled alert should be looked at immediately, not one interval later.
    if validated.enabled and not was_enabled:
        alert.next_check_at = datetime.now(timezone.utc)
        alert.state = "ok"

    await db.commit()
    await db.refresh(alert)

    names = await _workflow_names(db, [alert.workflow_id, alert.notify_workflow_id])
    return _to_response(
        alert,
        current_user_id=current_user.id,
        workflow_name=names.get(alert.workflow_id) if alert.workflow_id else None,
        notify_workflow_name=(
            names.get(alert.notify_workflow_id) if alert.notify_workflow_id else None
        ),
    )


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()


@router.post("/{alert_id}/test", response_model=AlertPreviewResponse)
async def test_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertPreviewResponse:
    """Evaluate a saved alert right now. Does not fire and does not write an event."""
    alert = await get_accessible_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    observation, window_start, window_end = await observe(db, alert)
    return AlertPreviewResponse(
        observed_value=float(observation.observed_value or 0.0),
        threshold_value=float(observation.threshold_value),
        would_fire_now=observation.breached,
        window_start=window_start,
        window_end=window_end,
        context=observation.context,
        backtest_fire_count=0,
        backtest_max_observed=float(observation.observed_value or 0.0),
        lookback_hours=0,
    )


@router.get("/{alert_id}/events", response_model=AlertEventListResponse)
async def list_alert_events(
    alert_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertEventListResponse:
    alert = await get_accessible_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    total_result = await db.execute(
        select(func.count()).select_from(AlertEvent).where(AlertEvent.alert_id == alert_id)
    )
    unack_result = await db.execute(
        select(func.count())
        .select_from(AlertEvent)
        .where(AlertEvent.alert_id == alert_id, AlertEvent.acknowledged_at.is_(None))
    )
    result = await db.execute(
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert_id)
        .order_by(AlertEvent.triggered_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return AlertEventListResponse(
        items=[
            _event_to_response(event, alert.name, alert.alert_type)
            for event in result.scalars().all()
        ],
        total=int(total_result.scalar() or 0),
        unacknowledged=int(unack_result.scalar() or 0),
    )


@router.get("/{alert_id}/shares", response_model=list[AlertShareEntry])
async def list_alert_shares(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AlertShareEntry]:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    result = await db.execute(
        select(AlertShare, User.email)
        .join(User, User.id == AlertShare.user_id)
        .where(AlertShare.alert_id == alert_id)
    )
    return [
        AlertShareEntry(id=share.id, user_id=share.user_id, user_email=email)
        for share, email in result.all()
    ]


@router.post("/{alert_id}/shares", response_model=AlertShareEntry, status_code=201)
async def create_alert_share(
    alert_id: uuid.UUID,
    payload: AlertShareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertShareEntry:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    user_result = await db.execute(select(User).where(User.email == payload.user_email))
    target = user_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Alert is already owned by this user")

    existing = await db.execute(
        select(AlertShare).where(AlertShare.alert_id == alert_id, AlertShare.user_id == target.id)
    )
    share = existing.scalar_one_or_none()
    if share is None:
        share = AlertShare(alert_id=alert_id, user_id=target.id)
        db.add(share)
        await db.commit()
        await db.refresh(share)

    return AlertShareEntry(id=share.id, user_id=share.user_id, user_email=target.email)


@router.delete("/{alert_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_share(
    alert_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    result = await db.execute(
        select(AlertShare).where(AlertShare.alert_id == alert_id, AlertShare.user_id == user_id)
    )
    share = result.scalar_one_or_none()
    if share is not None:
        await db.delete(share)
        await db.commit()


@router.get("/{alert_id}/team-shares", response_model=list[AlertTeamShareEntry])
async def list_alert_team_shares(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AlertTeamShareEntry]:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    result = await db.execute(
        select(AlertTeamShare, Team.name)
        .join(Team, Team.id == AlertTeamShare.team_id)
        .where(AlertTeamShare.alert_id == alert_id)
    )
    return [
        AlertTeamShareEntry(id=share.id, team_id=share.team_id, team_name=name)
        for share, name in result.all()
    ]


@router.post("/{alert_id}/team-shares", response_model=AlertTeamShareEntry, status_code=201)
async def create_alert_team_share(
    alert_id: uuid.UUID,
    payload: AlertTeamShareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertTeamShareEntry:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    team_result = await db.execute(select(Team).where(Team.id == payload.team_id))
    team = team_result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    existing = await db.execute(
        select(AlertTeamShare).where(
            AlertTeamShare.alert_id == alert_id, AlertTeamShare.team_id == payload.team_id
        )
    )
    share = existing.scalar_one_or_none()
    if share is None:
        share = AlertTeamShare(alert_id=alert_id, team_id=payload.team_id)
        db.add(share)
        await db.commit()
        await db.refresh(share)

    return AlertTeamShareEntry(id=share.id, team_id=share.team_id, team_name=team.name)


@router.delete("/{alert_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_team_share(
    alert_id: uuid.UUID,
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    alert = await get_owned_alert(db, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    result = await db.execute(
        select(AlertTeamShare).where(
            AlertTeamShare.alert_id == alert_id, AlertTeamShare.team_id == team_id
        )
    )
    share = result.scalar_one_or_none()
    if share is not None:
        await db.delete(share)
        await db.commit()


def _time_range_start(time_range: str) -> datetime | None:
    if time_range == "all":
        return None
    hours = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}[time_range]
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _event_to_response(event: AlertEvent, alert_name: str, alert_type: str) -> AlertEventResponse:
    return AlertEventResponse(
        id=event.id,
        alert_id=event.alert_id,
        alert_name=alert_name,
        alert_type=alert_type,
        triggered_at=event.triggered_at,
        observed_value=event.observed_value,
        threshold_value=event.threshold_value,
        window_start=event.window_start,
        window_end=event.window_end,
        context=event.context,
        acknowledged_at=event.acknowledged_at,
        notify_execution_id=event.notify_execution_id,
        notify_status=event.notify_status,
    )
