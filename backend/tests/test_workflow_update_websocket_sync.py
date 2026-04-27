"""Tests for immediate WebSocket trigger resync after workflow saves."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


if __name__ == "__main__":
    unittest.main()
