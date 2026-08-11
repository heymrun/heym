"""Alert evaluation: claiming, observation, state machine, notify dispatch.

Metric computation is NOT here - it lives in ``types/`` behind ``registry.py``.
This module owns everything that is the same for every alert type.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import get_accessible_workflow_ids
from app.db.models import Alert, AlertEvent, ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.models.alert_schemas import describe_condition, parse_alert_config
from app.services.alerts.context import AlertEvaluationContext, AlertObservation
from app.services.alerts.registry import get_alert_handler

logger = logging.getLogger("alert_evaluator")

CLAIM_BATCH_SIZE = 50

# Notify tasks are kept referenced so the event loop does not garbage-collect a
# still-running dispatch. asyncio holds only weak references to bare tasks.
_notify_tasks: set[asyncio.Task] = set()


async def resolve_scope_workflow_ids(db: AsyncSession, alert: Any) -> list[uuid.UUID]:
    """Workflow ids this alert measures.

    System scope resolves to the workflows the OWNER can access, not the whole
    instance - a shared alert must not leak metrics for workflows the viewer
    cannot open.
    """
    if alert.scope == "workflow":
        return [alert.workflow_id] if alert.workflow_id else []
    return await get_accessible_workflow_ids(db, alert.owner_id)


async def observe(
    db: AsyncSession, alert: Any, *, now: datetime | None = None
) -> tuple[AlertObservation, datetime, datetime]:
    """Compute the alert's metric over its window. Does not mutate anything."""
    window_end = now or datetime.now(timezone.utc)
    config = parse_alert_config(alert.alert_type, alert.config)
    window_start = window_end - timedelta(minutes=config.window_minutes)

    ctx = AlertEvaluationContext(
        db=db,
        owner_id=alert.owner_id,
        workflow_ids=await resolve_scope_workflow_ids(db, alert),
        window_start=window_start,
        window_end=window_end,
        config=config,
    )
    handler = get_alert_handler(alert.alert_type)
    observation = await handler(ctx)
    return observation, window_start, window_end


def next_state(*, breached: bool) -> str:
    return "triggered" if breached else "ok"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def should_fire(alert: Any, *, breached: bool, now: datetime) -> bool:
    """Whether this evaluation writes an event and dispatches a notification.

    Without this gate, a 60-second check interval on a genuinely broken workflow
    produces 60 events and 60 notify runs per hour, which is how alerting gets
    muted. The default ``on_recovery`` mode fires once and then holds its tongue
    until the metric drops back under the threshold.
    """
    if not breached:
        return False
    if alert.state != "triggered":
        return True
    if alert.renotify_mode != "cooldown":
        return False
    if alert.cooldown_minutes is None or alert.last_triggered_at is None:
        return False
    return now - _as_utc(alert.last_triggered_at) >= timedelta(minutes=alert.cooldown_minutes)


def should_dispatch_notify(alert: Any) -> bool:
    """False when there is no notify workflow, or when it is the alert's own workflow.

    An execution_count alert on workflow A that notifies workflow A is a runaway
    loop - each notification adds an execution, which raises the count.
    """
    if alert.notify_workflow_id is None:
        return False
    return alert.notify_workflow_id != alert.workflow_id


def build_notify_payload(
    alert: Any,
    *,
    observed_value: float,
    threshold_value: float,
    window_start: datetime,
    window_end: datetime,
    context: dict[str, Any],
    workflows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The body a notify workflow receives.

    ``workflows`` is the one place a workflow appears: every workflow that
    contributed to the reading, each with its own share of the number. Always an
    array, empty rather than null when nothing is attributable, and single-element
    under workflow scope. There is deliberately no singular ``workflow_id``: it was
    null under system scope, which is exactly when the question matters most.
    """
    config = parse_alert_config(alert.alert_type, alert.config)
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "alert_type": alert.alert_type,
        "condition": describe_condition(alert.alert_type, alert.config),
        "scope": alert.scope,
        "workflows": workflows or [],
        "observed_value": observed_value,
        "threshold_value": threshold_value,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_minutes": config.window_minutes,
        "context": context,
    }


async def _run_notify_workflow(
    alert_id: uuid.UUID,
    event_id: uuid.UUID,
    notify_workflow_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Execute the notify workflow and record the outcome on the event row.

    Runs in its own session and swallows every exception. A broken notify
    workflow must never stop the evaluator loop - the record of the firing
    matters more than the delivery of it.

    Mirrors ``error_workflow_runner.maybe_run_error_workflow``: ``execute_workflow``
    is synchronous and is called through ``asyncio.to_thread``, and the caller
    writes its own ``ExecutionHistory`` row.
    """
    from app.api.workflows import collect_referenced_workflows, get_credentials_context
    from app.services.global_variables_service import get_global_variables_context
    from app.services.workflow_executor import execute_workflow

    status = "failed"
    execution_id: uuid.UUID | None = None
    try:
        async with async_session_maker() as db:
            wf_result = await db.execute(select(Workflow).where(Workflow.id == notify_workflow_id))
            target = wf_result.scalar_one_or_none()
            if target is None:
                status = "skipped"
            else:
                actor_user_id = target.owner_id
                inputs = {"headers": {}, "query": {}, "body": payload}
                workflow_cache = await collect_referenced_workflows(
                    db, target.nodes, actor_user_id=actor_user_id
                )
                credentials_context = await get_credentials_context(db, actor_user_id)
                global_variables_context = await get_global_variables_context(db, actor_user_id)

                result = await asyncio.to_thread(
                    execute_workflow,
                    workflow_id=target.id,
                    nodes=target.nodes,
                    edges=target.edges,
                    inputs=inputs,
                    workflow_cache=workflow_cache,
                    test_run=False,
                    credentials_context=credentials_context,
                    global_variables_context=global_variables_context,
                    trace_user_id=actor_user_id,
                    actor_user_id=actor_user_id,
                )

                history = ExecutionHistory(
                    workflow_id=target.id,
                    inputs=inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source="ALERT",
                )
                db.add(history)
                await db.flush()
                execution_id = history.id
                await db.commit()
                status = "succeeded" if result.status != "error" else "failed"
    except Exception:  # noqa: BLE001 - delivery failure must not break evaluation
        logger.exception("Alert %s notify workflow failed", alert_id)
        status = "failed"

    try:
        async with async_session_maker() as db:
            await db.execute(
                update(AlertEvent)
                .where(AlertEvent.id == event_id)
                .values(notify_status=status, notify_execution_id=execution_id)
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Could not record notify status for alert event %s", event_id)


def dispatch_notify(alert: Any, event_id: uuid.UUID, payload: dict[str, Any]) -> None:
    """Start the notify workflow in the background, keeping a strong task reference."""
    task = asyncio.create_task(
        _run_notify_workflow(alert.id, event_id, alert.notify_workflow_id, payload)
    )
    _notify_tasks.add(task)
    task.add_done_callback(_notify_tasks.discard)


async def claim_due_alerts(db: AsyncSession, *, now: datetime) -> list[Any]:
    """Atomically claim up to CLAIM_BATCH_SIZE alerts that are due.

    The scheduler loop is leader-gated, but leadership can hand off mid-pass -
    that is exactly what caused the cron duplicate-fire incident. Advancing
    ``next_check_at`` inside the same statement as the selection, under
    ``FOR UPDATE SKIP LOCKED``, means a second worker that briefly believes it is
    leader claims nothing rather than double-firing.
    """
    due_ids = (
        select(Alert.id)
        .where(Alert.enabled.is_(True), Alert.next_check_at <= now)
        .order_by(Alert.next_check_at)
        .limit(CLAIM_BATCH_SIZE)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    result = await db.execute(
        update(Alert)
        .where(Alert.id.in_(due_ids))
        .values(
            # make_interval(years, months, weeks, days, hours, mins, secs) keeps the
            # per-row interval in SQL. Multiplying a Python timedelta by the column
            # compiles but fails at bind time: asyncpg tries to encode the timedelta
            # as a timestamp parameter.
            next_check_at=now + func.make_interval(0, 0, 0, 0, 0, 0, Alert.check_interval_seconds),
            last_evaluated_at=now,
        )
        .returning(Alert)
        .execution_options(synchronize_session=False)
    )
    claimed = list(result.scalars().all())
    await db.commit()
    return claimed


async def evaluate_alert(db: AsyncSession, alert: Any, *, now: datetime) -> bool:
    """Evaluate one claimed alert. Returns True when it fired.

    Never raises: one broken alert must not stop the batch.
    """
    try:
        observation, window_start, window_end = await observe(db, alert, now=now)
    except Exception:  # noqa: BLE001
        logger.exception("Alert %s evaluation failed", getattr(alert, "id", "?"))
        return False

    if observation.observed_value is None:
        # Not enough data to judge. Leave state and last_observed_value alone
        # rather than recording a misleading zero.
        await db.commit()
        return False

    breached = observation.breached
    fired = should_fire(alert, breached=breached, now=now)

    alert.last_observed_value = float(observation.observed_value)
    alert.state = next_state(breached=breached)

    event_id: uuid.UUID | None = None
    if fired:
        event_id = uuid.uuid4()
        alert.last_triggered_at = now
        db.add(
            AlertEvent(
                id=event_id,
                alert_id=alert.id,
                triggered_at=now,
                observed_value=float(observation.observed_value),
                threshold_value=float(observation.threshold_value),
                window_start=window_start,
                window_end=window_end,
                context=observation.context,
                notify_status="queued" if should_dispatch_notify(alert) else "skipped",
            )
        )

    await db.commit()

    # Dispatch only after the event row is committed. The record of the firing
    # must survive even if delivery fails.
    if fired and event_id is not None and should_dispatch_notify(alert):
        # One query for every contributing workflow, so a system-scope firing can
        # name the workflows behind the number.
        contributions = observation.contributing_workflows
        names: dict[uuid.UUID, str] = {}
        if contributions:
            name_result = await db.execute(
                select(Workflow.id, Workflow.name).where(Workflow.id.in_(list(contributions)))
            )
            names = {row[0]: row[1] for row in name_result.all()}

        payload = build_notify_payload(
            alert,
            observed_value=float(observation.observed_value),
            threshold_value=float(observation.threshold_value),
            window_start=window_start,
            window_end=window_end,
            context=observation.context,
            workflows=[
                {"id": str(workflow_id), "name": names[workflow_id], "value": value}
                for workflow_id, value in sorted(
                    contributions.items(), key=lambda item: item[1], reverse=True
                )
                if workflow_id in names
            ],
        )
        dispatch_notify(alert, event_id, payload)

    return fired


async def evaluate_due_alerts() -> int:
    """One full evaluation pass. Returns how many alerts fired."""
    fired = 0
    now = datetime.now(timezone.utc)
    async with async_session_maker() as db:
        claimed = await claim_due_alerts(db, now=now)
        for alert in claimed:
            if await evaluate_alert(db, alert, now=now):
                fired += 1
    return fired
