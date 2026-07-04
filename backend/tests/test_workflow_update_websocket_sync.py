"""Tests for immediate WebSocket trigger resync after workflow saves."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.workflows import update_workflow
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate


class WorkflowUpdateWebSocketSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_workflow_commits_and_requests_websocket_sync(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            name="Socket workflow",
            description=None,
            nodes=[
                {
                    "id": "socket-node",
                    "type": "websocketTrigger",
                    "data": {"label": "socketEvent", "websocketUrl": "wss://old.example.com"},
                }
            ],
            edges=[],
            auth_type=WorkflowAuthType.anonymous,
            auth_header_key=None,
            auth_header_value=None,
            webhook_body_mode=WebhookBodyMode.generic,
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            sse_enabled=False,
            sse_node_config=None,
            allow_anonymous=True,
            owner_id=owner_id,
            folder_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        current_user = SimpleNamespace(id=owner_id)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        db.add = lambda _row: None
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        payload = WorkflowUpdate(
            nodes=[
                {
                    "id": "socket-node",
                    "type": "websocketTrigger",
                    "data": {"label": "socketEvent", "websocketUrl": "wss://new.example.com"},
                }
            ],
            edges=[],
        )

        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.workflows._build_workflow_response",
                return_value={"id": str(workflow_id)},
            ),
            patch(
                "app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"
            ) as request_sync_mock,
        ):
            response = await update_workflow(
                workflow_id=workflow_id,
                workflow_data=payload,
                current_user=current_user,
                db=db,
            )

        self.assertEqual(response, {"id": str(workflow_id)})
        db.commit.assert_awaited_once()
        request_sync_mock.assert_called_once_with()

    async def test_dashboard_widget_workflow_update_invalidates_widget_cache(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            kind="dashboard_widget",
            name="Widget workflow",
            description=None,
            nodes=[
                {
                    "id": "chart",
                    "type": "chartOutput",
                    "data": {"chartType": "bar"},
                }
            ],
            edges=[],
            auth_type=WorkflowAuthType.anonymous,
            auth_header_key=None,
            auth_header_value=None,
            webhook_body_mode=WebhookBodyMode.generic,
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            sse_enabled=False,
            sse_node_config=None,
            allow_anonymous=True,
            owner_id=owner_id,
            folder_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        widget = SimpleNamespace(
            workflow_id=workflow_id,
            title="Widget workflow",
            description=None,
            chart_type="bar",
            cached_payload={"type": "bar"},
            cached_at=datetime.now(timezone.utc),
            cached_workflow_version="old",
        )
        current_user = SimpleNamespace(id=owner_id)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: widget),
                SimpleNamespace(scalar=lambda: 0),
            ]
        )
        db.add = lambda _row: None
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        payload = WorkflowUpdate(
            nodes=[
                {
                    "id": "chart",
                    "type": "chartOutput",
                    "data": {"chartType": "line"},
                }
            ],
            edges=[],
        )

        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.workflows._build_workflow_response",
                return_value={"id": str(workflow_id)},
            ),
            patch("app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"),
        ):
            await update_workflow(
                workflow_id=workflow_id,
                workflow_data=payload,
                current_user=current_user,
                db=db,
            )

        self.assertEqual(widget.chart_type, "line")
        self.assertIsNone(widget.cached_payload)
        self.assertIsNone(widget.cached_at)
        self.assertIsNone(widget.cached_workflow_version)

    async def test_dashboard_widget_workflow_update_rejects_trigger_nodes(self) -> None:
        workflow_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            kind="dashboard_widget",
            name="Widget workflow",
            description=None,
            nodes=[
                {
                    "id": "chart",
                    "type": "chartOutput",
                    "data": {"chartType": "bar"},
                }
            ],
            edges=[],
            auth_type=WorkflowAuthType.anonymous,
            auth_header_key=None,
            auth_header_value=None,
            webhook_body_mode=WebhookBodyMode.generic,
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            sse_enabled=False,
            sse_node_config=None,
            allow_anonymous=True,
            owner_id=owner_id,
            folder_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        current_user = SimpleNamespace(id=owner_id)
        db = AsyncMock()
        db.commit = AsyncMock()
        payload = WorkflowUpdate(
            nodes=[
                {"id": "input", "type": "textInput", "data": {"label": "input"}},
                {"id": "chart", "type": "chartOutput", "data": {"chartType": "bar"}},
            ],
            edges=[{"id": "e", "source": "input", "target": "chart"}],
        )

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await update_workflow(
                    workflow_id=workflow_id,
                    workflow_data=payload,
                    current_user=current_user,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("input (textInput)", ctx.exception.detail)
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
