"""Delivering Heym platform events to subscribing workflows.

The dispatcher polls rather than listening. Polling costs at most five seconds of
latency and survives a worker that was down when the event was published, which a
NOTIFY-only design would not - and ``heym.started`` is published at exactly the
moment workers are coming up.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import HeymEvent, Workflow
from app.db.session import async_session_maker
from app.services import heym_event_service

logger = logging.getLogger("heym_event_dispatcher")

DISPATCH_INTERVAL_SECONDS = 5
# Bounds backlog replay after downtime, the same role the cron scheduler's misfire
# grace plays: an event older than this is kept for inspection but never delivered.
DISPATCH_LOOKBACK_MINUTES = 5
CLEANUP_INTERVAL_MINUTES = 60


def find_heym_trigger_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the active ``heymTrigger`` nodes in a workflow."""
    return [
        node
        for node in nodes or []
        if node.get("type") == "heymTrigger"
        and node.get("data", {}).get("active", True) is not False
    ]


def node_accepts_event(node: dict[str, Any], event_name: str) -> bool:
    """Return whether the node subscribes to this event name.

    An empty or absent ``eventNames`` list means every event.
    """
    selected = node.get("data", {}).get("eventNames")
    if not selected:
        return True
    return event_name in selected


def event_visible_to_owner(
    event_owner_id: uuid.UUID | None, workflow_owner_id: uuid.UUID | None
) -> bool:
    """Return whether a workflow's owner may receive this event.

    Events with no owner are instance-wide and reach everyone; owned events stay
    with their owner.
    """
    if event_owner_id is None:
        return True
    return event_owner_id == workflow_owner_id


def build_trigger_inputs(node_id: str, events: list[Any]) -> dict[str, Any]:
    """Build the workflow inputs for one batched delivery.

    Delivery is always a list. A burst inside one poll window becomes one run, and
    a lone event still arrives as a one-element array so downstream expressions
    never have to branch on shape.
    """
    ordered = sorted(events, key=lambda event: event.created_at)
    return {
        "triggered_by": "heym_event",
        "trigger_node_id": node_id,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "events": [
            {
                "id": str(event.id),
                "name": event.name,
                "payload": event.payload or {},
                "workflow_id": str(event.workflow_id) if event.workflow_id else None,
                "created_at": event.created_at.isoformat(),
            }
            for event in ordered
        ],
    }


class HeymEventDispatcher:
    """Polls the event log and starts a run for every subscribing trigger node."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._worker_id = str(os.getpid())
        self._last_cleanup_at: datetime | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Heym event dispatcher started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Heym event dispatcher stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Heym event dispatch tick failed: %s", e)
            await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)

    async def _tick(self) -> None:
        workflows = await self._get_subscribing_workflows()
        if workflows:
            events = await self._get_recent_events()
            if events:
                for workflow in workflows:
                    await self._dispatch_workflow(workflow, events)
        await self._maybe_cleanup()

    async def _get_subscribing_workflows(self) -> list[Workflow]:
        async with async_session_maker() as db:
            result = await db.execute(select(Workflow))
            all_workflows = result.scalars().all()
        return [
            workflow for workflow in all_workflows if find_heym_trigger_nodes(workflow.nodes or [])
        ]

    async def _get_recent_events(self) -> list[HeymEvent]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=DISPATCH_LOOKBACK_MINUTES)
        async with async_session_maker() as db:
            result = await db.execute(
                select(HeymEvent)
                .where(HeymEvent.created_at >= cutoff)
                .order_by(HeymEvent.created_at.asc())
            )
            return list(result.scalars().all())

    async def _dispatch_workflow(self, workflow: Workflow, events: list[HeymEvent]) -> None:
        """Claim and deliver every matching event to each subscribing node."""
        for node in find_heym_trigger_nodes(workflow.nodes or []):
            node_id = str(node.get("id", "")).strip()
            if not node_id:
                continue

            claimed: list[HeymEvent] = []
            for event in events:
                if not event_visible_to_owner(event.owner_id, workflow.owner_id):
                    continue
                if not node_accepts_event(node, event.name):
                    continue
                if await heym_event_service.claim_heym_event(
                    event_id=event.id,
                    workflow_id=workflow.id,
                    node_id=node_id,
                    worker_id=self._worker_id,
                ):
                    claimed.append(event)

            if not claimed:
                continue

            logger.info(
                "Delivering %d heym event(s) to workflow %s node %s",
                len(claimed),
                workflow.id,
                node_id,
            )
            try:
                await self._run_workflow(workflow, node_id, build_trigger_inputs(node_id, claimed))
            except Exception as e:
                # The claim is inserted before the run, so an interrupted delivery -
                # a reload, a crash, an unexpected error - would otherwise consume the
                # event forever. Release the claims so a later tick can retry, and stay
                # inside this node's loop so one bad workflow cannot stop the others.
                logger.error(
                    "Heym event delivery failed for workflow %s node %s, releasing %d claim(s): %s",
                    workflow.id,
                    node_id,
                    len(claimed),
                    e,
                )
                await heym_event_service.release_heym_event_claims(
                    event_ids=[event.id for event in claimed],
                    workflow_id=workflow.id,
                    node_id=node_id,
                )

    async def _run_workflow(self, workflow: Workflow, node_id: str, inputs: dict[str, Any]) -> None:
        """Execute the workflow and persist the run, mirroring the IMAP trigger."""
        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.api.workflows import (
            _persist_global_variables_from_execution,
            collect_referenced_workflows,
            get_credentials_context,
        )
        from app.db.models import ExecutionHistory
        from app.services.cluster.dispatch import dispatch_workflow
        from app.services.execution_cancellation import clear_execution, register_execution
        from app.services.global_variables_service import get_global_variables_context

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                logger.warning("Workflow %s disappeared before heym event execution", workflow.id)
                return

            workflow_cache = await collect_referenced_workflows(
                db, fresh_workflow.nodes, actor_user_id=fresh_workflow.owner_id
            )
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            execution_id = uuid.uuid4()
            cancel_event = register_execution(
                workflow_id=fresh_workflow.id,
                execution_id=execution_id,
                inputs=inputs,
                trigger_source="heym_event",
                actor_user_id=fresh_workflow.owner_id,
            )
            try:
                result = await dispatch_workflow(
                    workflow_id=fresh_workflow.id,
                    nodes=fresh_workflow.nodes,
                    edges=fresh_workflow.edges,
                    inputs=inputs,
                    workflow_cache=workflow_cache,
                    trigger_source="heym_event",
                    credentials_owner_id=fresh_workflow.owner_id,
                    execution_id=execution_id,
                    credentials_context=credentials_context,
                    global_variables_context=global_variables_context,
                    trace_user_id=fresh_workflow.owner_id,
                    actor_user_id=fresh_workflow.owner_id,
                    cancel_event=cancel_event,
                )
            finally:
                clear_execution(execution_id)

            # An offloaded run wrote its own history on the instance that ran it.
            if getattr(result, "history_written", False):
                logger.info(
                    "Workflow %s executed via Heym event trigger on another instance, status: %s",
                    fresh_workflow.id,
                    result.status,
                )
                return

            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=fresh_workflow.id,
                    inputs=inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source="heym_event",
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

            for sub_exec in result.sub_workflow_executions:
                db.add(
                    ExecutionHistory(
                        workflow_id=uuid.UUID(sub_exec.workflow_id),
                        inputs=sub_exec.inputs,
                        outputs=sub_exec.outputs,
                        node_results=sub_exec.node_results,
                        status=sub_exec.status,
                        execution_time_ms=sub_exec.execution_time_ms,
                        trigger_source=sub_exec.trigger_source,
                    )
                )
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

    async def _maybe_cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_cleanup_at is not None and now - self._last_cleanup_at < timedelta(
            minutes=CLEANUP_INTERVAL_MINUTES
        ):
            return
        self._last_cleanup_at = now
        try:
            async with async_session_maker() as db:
                deleted = await heym_event_service.cleanup_heym_events(db)
                await db.commit()
            if deleted:
                logger.info("Cleaned up %d expired heym event(s)", deleted)
        except Exception as e:
            logger.warning("Heym event cleanup failed: %s", e)


heym_event_dispatcher = HeymEventDispatcher()
