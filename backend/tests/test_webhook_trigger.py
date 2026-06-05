"""Unit tests for the generic webhook trigger endpoint."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from app.services.workflow_executor import WorkflowExecutor


def _make_request(
    body_bytes: bytes = b"",
    headers: dict[str, str] | None = None,
    query_string: bytes = b"",
    method: str = "POST",
) -> Request:
    """Build a minimal Starlette request."""
    scope = {
        "type": "http",
        "method": method,
        "path": "/api/webhooks/test",
        "headers": Headers(headers or {}).raw,
        "query_string": query_string,
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


class TestWebhookTriggerEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_known_webhook_node_delegates_to_workflow_execution(self) -> None:
        from app.api.webhooks import webhook_trigger

        node_id = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            nodes=[{"id": node_id, "type": "webhookTrigger", "data": {"label": "webhook"}}],
        )
        db = AsyncMock()

        request = _make_request(
            json.dumps({"event": "created"}).encode(),
            {"content-type": "application/json"},
            b"source=test",
        )
        expected_response = {"ok": True}

        with (
            patch(
                "app.api.webhooks._find_workflow_by_node_id",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.webhooks.execute_workflow_request",
                new=AsyncMock(return_value=expected_response),
            ) as execute_request,
        ):
            response = await webhook_trigger(
                node_id=node_id,
                request=request,
                background_tasks=MagicMock(),
                current_user=None,
                db=db,
            )

        self.assertEqual(response, expected_response)
        execute_request.assert_awaited_once()
        call_kwargs = execute_request.await_args.kwargs
        self.assertEqual(call_kwargs["workflow_id"], workflow_id)
        self.assertEqual(call_kwargs["request"], request)
        self.assertEqual(call_kwargs["current_user"], None)
        self.assertEqual(call_kwargs["db"], db)
        self.assertEqual(call_kwargs["default_trigger_source"], "webhook")

    async def test_unknown_node_returns_404(self) -> None:
        from app.api.webhooks import webhook_trigger

        with patch(
            "app.api.webhooks._find_workflow_by_node_id",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await webhook_trigger(
                    node_id="missing",
                    request=_make_request(),
                    background_tasks=MagicMock(),
                    current_user=None,
                    db=AsyncMock(),
                )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_non_webhook_node_returns_404(self) -> None:
        from app.api.webhooks import webhook_trigger

        node_id = str(uuid.uuid4())
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            nodes=[{"id": node_id, "type": "textInput", "data": {"label": "start"}}],
        )

        with patch(
            "app.api.webhooks._find_workflow_by_node_id",
            new=AsyncMock(return_value=workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await webhook_trigger(
                    node_id=node_id,
                    request=_make_request(),
                    background_tasks=MagicMock(),
                    current_user=None,
                    db=AsyncMock(),
                )

        self.assertEqual(ctx.exception.status_code, 404)


class TestWebhookTriggerExecutor(unittest.TestCase):
    def test_webhook_trigger_outputs_request_metadata(self) -> None:
        node = {
            "id": "webhook-1",
            "type": "webhookTrigger",
            "data": {"label": "webhook"},
        }
        executor = WorkflowExecutor(nodes=[node], edges=[])
        result = executor.execute(
            uuid.uuid4(),
            {
                "body": {"event": "created"},
                "headers": {"content-type": "application/json"},
                "query": {"source": "test"},
                "method": "POST",
                "triggered_at": "2026-06-05T12:00:00+00:00",
            },
        )

        self.assertEqual(result.status, "success")
        output = result.node_results[0]["output"]
        self.assertEqual(output["body"], {"event": "created"})
        self.assertEqual(output["headers"], {"content-type": "application/json"})
        self.assertEqual(output["query"], {"source": "test"})
        self.assertEqual(output["method"], "POST")
        self.assertEqual(output["triggered_at"], "2026-06-05T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
