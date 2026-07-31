"""Unit tests for the Cal.com Trigger webhook endpoint and node handler."""

import hashlib
import hmac
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from app.db.models import ExecutionHistory
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.cal_trigger_node import execute as execute_cal_trigger
from app.services.workflow_executor import ExecutionResult


def _make_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _make_request(body: bytes, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/cal/webhook/test",
        "headers": Headers(headers).raw,
        "query_string": b"",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class CalSignatureTests(unittest.TestCase):
    def test_accepts_hex_and_prefixed_signatures(self) -> None:
        from app.api.cal import _verify_cal_signature

        body = b'{"triggerEvent":"BOOKING_CREATED"}'
        signature = _make_signature("secret", body)
        self.assertTrue(_verify_cal_signature("secret", body, signature))
        self.assertTrue(_verify_cal_signature("secret", body, f"sha256={signature}"))

    def test_rejects_invalid_signature(self) -> None:
        from app.api.cal import _verify_cal_signature

        self.assertFalse(_verify_cal_signature("secret", b"{}", "bad-signature"))


class CalWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_webhook_schedules_workflow(self) -> None:
        from app.api.cal import cal_webhook

        node_id = str(uuid.uuid4())
        credential_id = str(uuid.uuid4())
        secret = "cal-webhook-secret"
        body = json.dumps(
            {
                "triggerEvent": "BOOKING_CREATED",
                "payload": {"uid": "booking-1"},
            }
        ).encode("utf-8")
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.nodes = [
            {
                "id": node_id,
                "type": "calTrigger",
                "data": {"credentialId": credential_id},
            }
        ]
        request = _make_request(
            body,
            {
                "content-type": "application/json",
                "x-cal-signature-256": _make_signature(secret, body),
            },
        )

        with (
            patch(
                "app.api.cal._find_workflow_by_node_id",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.cal._get_webhook_secret",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.api.cal._execute_workflow_background",
                new=AsyncMock(),
            ) as execute_background,
        ):
            response = await cal_webhook(node_id, request)

        self.assertEqual(response, {"ok": True})
        execute_background.assert_called_once()

    async def test_invalid_signature_is_rejected(self) -> None:
        from app.api.cal import cal_webhook

        node_id = str(uuid.uuid4())
        workflow = MagicMock()
        workflow.nodes = [
            {
                "id": node_id,
                "type": "calTrigger",
                "data": {"credentialId": str(uuid.uuid4())},
            }
        ]
        request = _make_request(
            b'{"triggerEvent":"BOOKING_CREATED"}',
            {"x-cal-signature-256": "invalid"},
        )

        with (
            patch(
                "app.api.cal._find_workflow_by_node_id",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.cal._get_webhook_secret",
                new=AsyncMock(return_value="secret"),
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                await cal_webhook(node_id, request)

        self.assertEqual(context.exception.status_code, 403)

    async def test_missing_credential_fails_closed(self) -> None:
        from app.api.cal import cal_webhook

        node_id = str(uuid.uuid4())
        workflow = MagicMock()
        workflow.nodes = [{"id": node_id, "type": "calTrigger", "data": {}}]
        request = _make_request(b"{}", {})

        with patch(
            "app.api.cal._find_workflow_by_node_id",
            new=AsyncMock(return_value=workflow),
        ):
            with self.assertRaises(HTTPException) as context:
                await cal_webhook(node_id, request)

        self.assertEqual(context.exception.status_code, 400)

    async def test_background_execution_persists_cal_inputs(self) -> None:
        from app.api.cal import _execute_workflow_background

        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Cal.com workflow",
            nodes=[],
            edges=[],
        )
        added_rows: list[object] = []
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)),
            add=added_rows.append,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=12.3,
            node_results=[],
            sub_workflow_executions=[],
        )
        event = {
            "triggerEvent": "BOOKING_CREATED",
            "payload": {"uid": "booking-1"},
        }

        with (
            patch("app.api.cal.async_session_maker") as session_maker,
            patch("app.api.cal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.cal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.cal.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.cal.execute_workflow", return_value=execution_result),
            patch("app.api.cal.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.cal._persist_global_variables_from_execution", AsyncMock()),
        ):
            session = AsyncMock()
            session.__aenter__.return_value = db
            session.__aexit__.return_value = None
            session_maker.return_value = session

            await _execute_workflow_background(
                workflow,
                "cal-node",
                event,
                {"content-type": "application/json"},
            )

        history = next(row for row in added_rows if isinstance(row, ExecutionHistory))
        self.assertEqual(history.trigger_source, "Cal.com")
        self.assertEqual(history.inputs["triggered_by"], "Cal.com")
        self.assertEqual(history.inputs["trigger_node_id"], "cal-node")
        self.assertEqual(history.inputs["trigger_event"], "BOOKING_CREATED")
        self.assertEqual(history.inputs["payload"]["uid"], "booking-1")
        self.assertIn("triggered_at", history.inputs)


class CalTriggerNodeTests(unittest.TestCase):
    def test_handler_exposes_event_payload(self) -> None:
        event = {
            "triggerEvent": "BOOKING_CANCELLED",
            "payload": {"uid": "booking-2"},
        }
        context = NodeExecutionContext(
            executor=SimpleNamespace(),
            node_id="cal-node",
            inputs={},
            allow_branch_skip=False,
            start_time=0.0,
            node={},
            node_type="calTrigger",
            node_data={
                "_initial_inputs": {
                    "event": event,
                    "trigger_event": "BOOKING_CANCELLED",
                    "payload": event["payload"],
                    "headers": {"content-type": "application/json"},
                    "triggered_at": "2026-07-31T00:00:00+00:00",
                }
            },
            node_label="calTrigger",
        )

        output = execute_cal_trigger(context)

        self.assertEqual(output["event"], event)
        self.assertEqual(output["triggerEvent"], "BOOKING_CANCELLED")
        self.assertEqual(output["payload"]["uid"], "booking-2")


if __name__ == "__main__":
    unittest.main()
