"""Leader-only outbound WebSocket trigger manager."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import websockets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.exceptions import ConnectionClosed

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import ExecutionHistory, Workflow
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.global_variables_service import get_global_variables_context
from app.services.websocket_utils import (
    build_websocket_connect_kwargs,
    parse_websocket_message,
)
from app.services.workflow_executor import execute_workflow

logger = logging.getLogger("websocket_trigger")


@dataclass(frozen=True)
class WebSocketTriggerConfig:
    """Static runtime configuration for one trigger node."""

    workflow_id: uuid.UUID
    node_id: str
    url: str
    headers: str
    subprotocols: str
    retry_enabled: bool
    retry_wait_seconds: int
    event_names: tuple[str, ...]


@dataclass
class WebSocketTriggerState:
    """Mutable runner state kept by the manager."""

    config: WebSocketTriggerConfig
    task: asyncio.Task[None]
    permanently_stopped: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_event_names(raw_event_names: Any) -> tuple[str, ...]:
    if not isinstance(raw_event_names, list):
        return ("onMessage",)
    normalized = tuple(
        event_name
        for event_name in raw_event_names
        if event_name in {"onMessage", "onConnected", "onClosed"}
    )
    return normalized or ("onMessage",)


def _infer_close_initiator(exc: ConnectionClosed) -> str:
    if exc.rcvd is not None and exc.sent is None:
        return "server"
    if exc.sent is not None and exc.rcvd is None:
        return "client"
    if exc.rcvd is not None and exc.sent is not None:
        if exc.rcvd_then_sent is True:
            return "server"
        if exc.rcvd_then_sent is False:
            return "client"
    return "unknown"


class WebSocketTriggerManager:
    """Maintains outbound client connections for active websocketTrigger nodes."""

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._triggers: dict[str, WebSocketTriggerState] = {}
        self._lock = asyncio.Lock()
        self._wake_event = asyncio.Event()
        self._was_leader = False
        self._sync_interval_seconds = 15

    def _get_node_key(self, workflow_id: uuid.UUID, node_id: str) -> str:
        return f"{workflow_id}_{node_id}"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._wake_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("WebSocket trigger manager started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        self._running = False
        self._wake_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._stop_all_triggers()
        logger.info("WebSocket trigger manager stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(5)
        while self._running:
            try:
                is_leader = lock_service.is_leader
                if is_leader and not self._was_leader:
                    logger.info("Becoming leader, starting WebSocket triggers...")
                    self._was_leader = True
                if not is_leader and self._was_leader:
                    logger.info("Lost leadership, stopping WebSocket triggers...")
                    await self._stop_all_triggers()
                    self._was_leader = False
                if is_leader:
                    await self._sync_triggers()
            except Exception as exc:
                logger.exception("Error in WebSocket trigger sync loop: %s", exc)
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self._sync_interval_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake_event.clear()

    def request_sync(self) -> None:
        """Wake the manager loop so workflow config changes apply immediately."""
        self._wake_event.set()

    async def _stop_all_triggers(self) -> None:
        async with self._lock:
            for key in list(self._triggers.keys()):
                await self._stop_trigger_locked(key)

    async def _stop_trigger_locked(self, key: str) -> None:
        state = self._triggers.pop(key, None)
        if state is None:
            return
        state.task.cancel()
        try:
            await state.task
        except asyncio.CancelledError:
            pass

    async def _sync_triggers(self) -> None:
        async with async_session_maker() as db:
            workflows = await self._get_workflows_with_websocket_trigger(db)

        desired_configs: dict[str, WebSocketTriggerConfig] = {}
        for workflow in workflows:
            for node in self._find_websocket_trigger_nodes(workflow.nodes):
                config = self._build_trigger_config(workflow.id, node)
                if config is None:
                    continue
                desired_configs[self._get_node_key(workflow.id, config.node_id)] = config

        async with self._lock:
            desired_keys = set(desired_configs)
            current_keys = set(self._triggers)

            for key in current_keys - desired_keys:
                await self._stop_trigger_locked(key)

            for key, config in desired_configs.items():
                existing = self._triggers.get(key)
                if existing is not None and existing.task.done():
                    if existing.permanently_stopped and existing.config == config:
                        continue
                    self._triggers.pop(key, None)
                    existing = None

                if existing is not None and existing.config == config:
                    continue

                if existing is not None:
                    await self._stop_trigger_locked(key)

                task = asyncio.create_task(self._run_trigger_loop(key, config))
                self._triggers[key] = WebSocketTriggerState(config=config, task=task)
                logger.info(
                    "Registered WebSocket trigger for workflow %s node %s",
                    config.workflow_id,
                    config.node_id,
                )

    async def _get_workflows_with_websocket_trigger(self, db: AsyncSession) -> list[Workflow]:
        result = await db.execute(select(Workflow))
        workflows = result.scalars().all()
        return [
            workflow for workflow in workflows if self._has_websocket_trigger_node(workflow.nodes)
        ]

    def _has_websocket_trigger_node(self, nodes: list[dict[str, Any]]) -> bool:
        return any(
            node.get("type") == "websocketTrigger"
            and node.get("data", {}).get("active", True) is not False
            for node in nodes
        )

    def _find_websocket_trigger_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            node
            for node in nodes
            if node.get("type") == "websocketTrigger"
            and node.get("data", {}).get("active", True) is not False
        ]

    def _build_trigger_config(
        self,
        workflow_id: uuid.UUID,
        node: dict[str, Any],
    ) -> WebSocketTriggerConfig | None:
        node_id = str(node.get("id", "")).strip()
        node_data = node.get("data", {})
        url = str(node_data.get("websocketUrl", "")).strip()
        if not node_id or not url:
            return None

        retry_wait_seconds_raw = node_data.get("retryWaitSeconds", 5)
        try:
            retry_wait_seconds = max(1, int(retry_wait_seconds_raw))
        except (TypeError, ValueError):
            retry_wait_seconds = 5

        return WebSocketTriggerConfig(
            workflow_id=workflow_id,
            node_id=node_id,
            url=url,
            headers=str(node_data.get("websocketHeaders", "") or ""),
            subprotocols=str(node_data.get("websocketSubprotocols", "") or ""),
            retry_enabled=bool(node_data.get("retryEnabled", True)),
            retry_wait_seconds=retry_wait_seconds,
            event_names=_normalize_event_names(node_data.get("websocketTriggerEvents")),
        )

    async def _run_trigger_loop(self, key: str, config: WebSocketTriggerConfig) -> None:
        has_connected_once = False

        while self._running:
            try:
                connect_kwargs = build_websocket_connect_kwargs(
                    config.headers,
                    config.subprotocols,
                )
                async with websockets.connect(config.url, **connect_kwargs) as websocket:
                    if "onConnected" in config.event_names:
                        await self._execute_workflow_for_event(
                            config.workflow_id,
                            config.node_id,
                            {
                                "eventName": "onConnected",
                                "triggered_at": _now_iso(),
                                "url": config.url,
                                "connection": {
                                    "reconnected": has_connected_once,
                                    "subprotocol": websocket.subprotocol,
                                },
                            },
                        )

                    has_connected_once = True

                    while self._running:
                        try:
                            message = await websocket.recv()
                        except ConnectionClosed as exc:
                            if "onClosed" in config.event_names and self._running:
                                await self._execute_workflow_for_event(
                                    config.workflow_id,
                                    config.node_id,
                                    {
                                        "eventName": "onClosed",
                                        "triggered_at": _now_iso(),
                                        "url": config.url,
                                        "close": {
                                            "initiatedBy": _infer_close_initiator(exc),
                                            "code": exc.code,
                                            "reason": exc.reason,
                                            "wasClean": exc.code == 1000,
                                            "reconnecting": config.retry_enabled,
                                        },
                                    },
                                )
                            break

                        if "onMessage" in config.event_names:
                            await self._execute_workflow_for_event(
                                config.workflow_id,
                                config.node_id,
                                {
                                    "eventName": "onMessage",
                                    "triggered_at": _now_iso(),
                                    "url": config.url,
                                    "message": parse_websocket_message(message),
                                },
                            )

                if not config.retry_enabled:
                    await self._mark_trigger_permanently_stopped(key)
                    return

                await asyncio.sleep(config.retry_wait_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "WebSocket trigger connection failed for workflow %s node %s: %s",
                    config.workflow_id,
                    config.node_id,
                    exc,
                )
                if not config.retry_enabled:
                    await self._mark_trigger_permanently_stopped(key)
                    return
                await asyncio.sleep(config.retry_wait_seconds)

    async def _mark_trigger_permanently_stopped(self, key: str) -> None:
        async with self._lock:
            state = self._triggers.get(key)
            if state is not None:
                state.permanently_stopped = True

    async def _execute_workflow_for_event(
        self,
        workflow_id: uuid.UUID,
        node_id: str,
        event_payload: dict[str, Any],
    ) -> None:
        inputs = {
            "triggered_by": "websocket",
            "trigger_node_id": node_id,
            **event_payload,
        }

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
            workflow = workflow_result.scalar_one_or_none()
            if not workflow:
                logger.warning("Workflow %s disappeared before WebSocket execution", workflow_id)
                return

            trigger_node = next(
                (node for node in workflow.nodes if str(node.get("id")) == node_id),
                None,
            )
            if trigger_node is None or trigger_node.get("data", {}).get("active") is False:
                logger.info(
                    "Skipping WebSocket trigger event for workflow %s node %s because it is inactive",
                    workflow_id,
                    node_id,
                )
                return

            workflow_cache = await collect_referenced_workflows(db, workflow.nodes)
            credentials_context = await get_credentials_context(db, workflow.owner_id)
            global_variables_context = await get_global_variables_context(db, workflow.owner_id)

            result = execute_workflow(
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs=inputs,
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=workflow.owner_id,
            )

            history_entry = ExecutionHistory(
                workflow_id=workflow.id,
                inputs=inputs,
                outputs=result.outputs,
                node_results=result.node_results,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                trigger_source="websocket",
            )
            db.add(history_entry)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
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
                workflow.owner_id,
                workflow.nodes,
                workflow_cache,
                result.node_results,
                result.sub_workflow_executions,
            )

            await db.commit()


websocket_trigger_manager = WebSocketTriggerManager()
