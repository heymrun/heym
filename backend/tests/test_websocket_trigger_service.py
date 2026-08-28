"""Unit tests for WebSocket trigger manager behavior."""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from app.db.models import ExecutionHistory
from app.services.ssrf_guard import SsrfBlockedError, SsrfResolutionError
from app.services.websocket_trigger_service import (
    WebSocketTriggerConfig,
    WebSocketTriggerManager,
    _infer_close_initiator,
)
from app.services.workflow_executor import ExecutionResult, SubWorkflowExecution


class WebSocketTriggerManagerConfigTests(unittest.TestCase):
    def test_build_trigger_config_uses_defaults(self) -> None:
        manager = WebSocketTriggerManager()
        workflow_id = uuid.uuid4()
        node = {
            "id": "socket-node",
            "type": "websocketTrigger",
            "data": {
                "label": "socketEvent",
                "websocketUrl": "wss://socket.example.com/feed",
                "websocketTriggerEvents": [],
            },
        }

        config = manager._build_trigger_config(workflow_id, node)

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.workflow_id, workflow_id)
        self.assertEqual(config.event_names, ("onMessage",))
        self.assertTrue(config.retry_enabled)
        self.assertEqual(config.retry_wait_seconds, 5)

    def test_infer_close_initiator_prefers_server_when_remote_closed_first(self) -> None:
        exc = ConnectionClosed(
            rcvd=Close(1000, "done"),
            sent=Close(1000, "done"),
            rcvd_then_sent=True,
        )

        self.assertEqual(_infer_close_initiator(exc), "server")

    def test_request_sync_sets_wake_event(self) -> None:
        manager = WebSocketTriggerManager()

        self.assertFalse(manager._wake_event.is_set())
        manager.request_sync()
        self.assertTrue(manager._wake_event.is_set())


class WebSocketTriggerRetryTests(unittest.IsolatedAsyncioTestCase):
    def _config(
        self,
        *,
        retry_enabled: bool = True,
        headers: str = "",
        subprotocols: str = "",
    ) -> WebSocketTriggerConfig:
        return WebSocketTriggerConfig(
            workflow_id=uuid.uuid4(),
            node_id="socket-node",
            url="wss://socket.example.com/feed",
            headers=headers,
            subprotocols=subprotocols,
            retry_enabled=retry_enabled,
            retry_wait_seconds=1,
            event_names=("onMessage",),
        )

    async def test_policy_block_stops_without_retrying(self) -> None:
        manager = WebSocketTriggerManager()
        manager._running = True
        mark_stopped = AsyncMock()

        with (
            patch(
                "app.services.websocket_trigger_service.open_guarded_websocket",
                new=AsyncMock(side_effect=SsrfBlockedError("private address")),
            ) as open_socket,
            patch.object(manager, "_mark_trigger_permanently_stopped", mark_stopped),
            patch("app.services.websocket_trigger_service.asyncio.sleep", new=AsyncMock()) as sleep,
            patch("app.services.websocket_trigger_service.logger.exception") as log_exception,
        ):
            await asyncio.wait_for(
                manager._run_trigger_loop("trigger-key", self._config()),
                timeout=0.5,
            )

        open_socket.assert_awaited_once()
        mark_stopped.assert_awaited_once_with("trigger-key")
        sleep.assert_not_awaited()
        log_exception.assert_not_called()

    async def test_invalid_header_configuration_stops_without_retrying(self) -> None:
        invalid_headers = (
            "{not-json",
            '{"Origin": "https://one.example", "origin": "https://two.example"}',
            '{"Authorization": "Bearer t\\r\\nHost: internal-admin"}',
        )

        for headers in invalid_headers:
            with self.subTest(headers=headers):
                manager = WebSocketTriggerManager()
                manager._running = True
                mark_stopped = AsyncMock()

                with (
                    patch(
                        "app.services.websocket_trigger_service.open_guarded_websocket",
                        new=AsyncMock(),
                    ) as open_socket,
                    patch.object(manager, "_mark_trigger_permanently_stopped", mark_stopped),
                    patch(
                        "app.services.websocket_trigger_service.asyncio.sleep",
                        new=AsyncMock(),
                    ) as sleep,
                    patch(
                        "app.services.websocket_trigger_service.logger.exception"
                    ) as log_exception,
                ):
                    await asyncio.wait_for(
                        manager._run_trigger_loop(
                            "trigger-key",
                            self._config(headers=headers),
                        ),
                        timeout=0.5,
                    )

                open_socket.assert_not_awaited()
                mark_stopped.assert_awaited_once_with("trigger-key")
                sleep.assert_not_awaited()
                log_exception.assert_not_called()

    async def test_invalid_subprotocol_configuration_stops_without_retrying(self) -> None:
        manager = WebSocketTriggerManager()
        manager._running = True
        mark_stopped = AsyncMock()

        with (
            patch(
                "app.services.websocket_trigger_service.open_guarded_websocket",
                new=AsyncMock(),
            ) as open_socket,
            patch.object(manager, "_mark_trigger_permanently_stopped", mark_stopped),
            patch(
                "app.services.websocket_trigger_service.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
            patch("app.services.websocket_trigger_service.logger.exception") as log_exception,
        ):
            await asyncio.wait_for(
                manager._run_trigger_loop(
                    "trigger-key",
                    self._config(subprotocols="chat proto"),
                ),
                timeout=0.5,
            )

        open_socket.assert_not_awaited()
        mark_stopped.assert_awaited_once_with("trigger-key")
        sleep.assert_not_awaited()
        log_exception.assert_not_called()

    async def test_resolution_failure_retries_without_traceback(self) -> None:
        manager = WebSocketTriggerManager()
        manager._running = True
        mark_stopped = AsyncMock()

        with (
            patch(
                "app.services.websocket_trigger_service.open_guarded_websocket",
                new=AsyncMock(
                    side_effect=[
                        SsrfResolutionError("temporary DNS failure"),
                        SsrfBlockedError("private address"),
                    ]
                ),
            ) as open_socket,
            patch.object(manager, "_mark_trigger_permanently_stopped", mark_stopped),
            patch("app.services.websocket_trigger_service.asyncio.sleep", new=AsyncMock()) as sleep,
            patch("app.services.websocket_trigger_service.logger.warning") as log_warning,
            patch("app.services.websocket_trigger_service.logger.exception") as log_exception,
        ):
            await manager._run_trigger_loop("trigger-key", self._config())

        self.assertEqual(open_socket.await_count, 2)
        sleep.assert_awaited_once_with(1)
        mark_stopped.assert_awaited_once_with("trigger-key")
        self.assertEqual(log_warning.call_count, 2)
        log_exception.assert_not_called()

    async def test_resolution_failure_stops_when_retry_is_disabled(self) -> None:
        manager = WebSocketTriggerManager()
        manager._running = True
        mark_stopped = AsyncMock()

        with (
            patch(
                "app.services.websocket_trigger_service.open_guarded_websocket",
                new=AsyncMock(side_effect=SsrfResolutionError("temporary DNS failure")),
            ) as open_socket,
            patch.object(manager, "_mark_trigger_permanently_stopped", mark_stopped),
            patch("app.services.websocket_trigger_service.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            await manager._run_trigger_loop(
                "trigger-key",
                self._config(retry_enabled=False),
            )

        open_socket.assert_awaited_once()
        mark_stopped.assert_awaited_once_with("trigger-key")
        sleep.assert_not_awaited()


class WebSocketTriggerExecutionHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_persists_websocket_trigger_source(self) -> None:
        manager = WebSocketTriggerManager()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        sub_workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Socket workflow",
            nodes=[
                {
                    "id": "socket-node",
                    "type": "websocketTrigger",
                    "data": {
                        "label": "socketEvent",
                        "websocketUrl": "wss://socket.example.com/feed",
                        "websocketTriggerEvents": ["onMessage"],
                    },
                }
            ],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)),
            add=add_row,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=18.4,
            node_results=[],
            sub_workflow_executions=[
                SubWorkflowExecution(
                    workflow_id=str(sub_workflow_id),
                    inputs={"source": "websocket"},
                    outputs={"done": True},
                    status="success",
                    execution_time_ms=4.2,
                    node_results=[],
                    workflow_name="Child workflow",
                )
            ],
        )

        event_payload = {
            "eventName": "onClosed",
            "triggered_at": "2026-04-21T10:00:00+00:00",
            "url": "wss://socket.example.com/feed",
            "close": {
                "initiatedBy": "server",
                "code": 1000,
                "reason": "normal shutdown",
                "wasClean": True,
                "reconnecting": True,
            },
        }

        with (
            patch(
                "app.services.websocket_trigger_service.async_session_maker"
            ) as mock_session_maker,
            patch(
                "app.services.websocket_trigger_service.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.websocket_trigger_service.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.websocket_trigger_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.websocket_trigger_service.dispatch_workflow",
                AsyncMock(return_value=execution_result),
            ),
            patch(
                "app.services.websocket_trigger_service.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.websocket_trigger_service._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = db
            mock_session.__aexit__.return_value = None
            mock_session_maker.return_value = mock_session

            await manager._execute_workflow_for_event(workflow_id, "socket-node", event_payload)

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 2)
        parent = next(row for row in history_rows if row.workflow_id == workflow_id)
        child = next(row for row in history_rows if row.workflow_id == sub_workflow_id)
        self.assertEqual(parent.trigger_source, "websocket")
        self.assertEqual(child.trigger_source, "SUB_WORKFLOW")
        self.assertEqual(parent.inputs["triggered_by"], "websocket")
        self.assertEqual(parent.inputs["eventName"], "onClosed")
        self.assertEqual(parent.inputs["close"]["initiatedBy"], "server")


if __name__ == "__main__":
    unittest.main()
