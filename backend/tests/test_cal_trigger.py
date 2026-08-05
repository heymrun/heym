"""Unit tests for the Cal.com Trigger webhook endpoint and node handler."""

import asyncio
import hashlib
import hmac
import json
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from app.db.models import CredentialType
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.cal_trigger_node import execute as execute_cal_trigger
from app.services.workflow_executor import ExecutionResult


def _make_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _make_request(body: bytes, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/cal/webhook/workflow/node",
        "headers": Headers(headers).raw,
        "query_string": b"",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _session_context(db: object) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def _workflow(node_id: str, credential_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Cal.com workflow",
        description=None,
        workflow_timeout_seconds=30,
        nodes=[
            {
                "id": node_id,
                "type": "calTrigger",
                "data": {"credentialId": credential_id},
            }
        ],
        edges=[],
    )


class CalSignatureTests(unittest.TestCase):
    def test_scoped_and_deprecated_legacy_webhook_routes_are_registered(self) -> None:
        from app.main import app

        paths = {route.path for route in app.router.routes}
        self.assertIn("/api/cal/webhook/{workflow_id}/{node_id}", paths)
        self.assertIn("/api/cal/webhook/{node_id}", paths)

    def test_accepts_hex_and_prefixed_signatures(self) -> None:
        from app.api.cal import _verify_cal_signature

        body = b'{"triggerEvent":"BOOKING_CREATED"}'
        signature = _make_signature("secret", body)
        self.assertTrue(_verify_cal_signature("secret", body, signature))
        self.assertTrue(_verify_cal_signature("secret", body, f"sha256={signature}"))

    def test_rejects_invalid_signature(self) -> None:
        from app.api.cal import _verify_cal_signature

        self.assertFalse(_verify_cal_signature("secret", b"{}", "bad-signature"))


class CalInputTests(unittest.TestCase):
    def test_wrapped_event_uses_nested_payload(self) -> None:
        from app.api.cal import _build_trigger_inputs

        event = {"triggerEvent": "BOOKING_CREATED", "payload": {"uid": "booking-1"}}
        inputs = _build_trigger_inputs("cal-node", event, {})
        self.assertEqual(inputs["payload"], {"uid": "booking-1"})

    def test_flat_meeting_event_uses_complete_body_as_payload(self) -> None:
        from app.api.cal import _build_trigger_inputs

        event = {
            "triggerEvent": "MEETING_STARTED",
            "uid": "booking-1",
            "idempotencyKey": "meeting-event-1",
        }
        inputs = _build_trigger_inputs("cal-node", event, {})
        self.assertIs(inputs["payload"], event)

    def test_deduplication_requires_delivery_identity(self) -> None:
        from app.api.cal import _deduplication_key

        self.assertIsNone(_deduplication_key("cal-node", {"content": "A booking was created"}))

    def test_deduplication_is_stable_for_identified_delivery(self) -> None:
        from app.api.cal import _deduplication_key

        event = {
            "triggerEvent": "BOOKING_CREATED",
            "createdAt": "2026-08-04T00:00:00Z",
        }
        self.assertEqual(
            _deduplication_key("cal-node", event),
            _deduplication_key("cal-node", event),
        )

    def test_idempotency_key_is_stable_when_payload_changes(self) -> None:
        from app.api.cal import _deduplication_key

        first = {"idempotencyKey": "delivery-1", "title": "Original"}
        retried = {"title": "Updated serialization", "idempotencyKey": "delivery-1"}

        self.assertEqual(
            _deduplication_key("cal-node", first),
            _deduplication_key("cal-node", retried),
        )

    def test_created_at_deduplication_uses_canonical_json(self) -> None:
        from app.api.cal import _deduplication_key

        first = {"createdAt": "2026-08-04T00:00:00Z", "payload": {"uid": "booking-1"}}
        reordered = {"payload": {"uid": "booking-1"}, "createdAt": "2026-08-04T00:00:00Z"}

        self.assertEqual(
            _deduplication_key("cal-node", first),
            _deduplication_key("cal-node", reordered),
        )


class CalCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_secret_requires_accessible_cal_credential(self) -> None:
        from app.api.cal import _get_webhook_secret

        owner_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        credential = SimpleNamespace(
            type=CredentialType.cal_trigger,
            encrypted_config="encrypted",
        )
        with (
            patch(
                "app.api.cal.get_accessible_credential",
                AsyncMock(return_value=credential),
            ) as get_credential,
            patch(
                "app.api.cal.decrypt_config",
                return_value={"webhook_secret": " secret "},
            ),
        ):
            secret = await _get_webhook_secret(MagicMock(), str(credential_id), owner_id)

        self.assertEqual(secret, "secret")
        get_credential.assert_awaited_once_with(unittest.mock.ANY, credential_id, owner_id)

    async def test_webhook_secret_rejects_inaccessible_credential(self) -> None:
        from app.api.cal import _get_webhook_secret

        with patch(
            "app.api.cal.get_accessible_credential",
            AsyncMock(return_value=None),
        ):
            secret = await _get_webhook_secret(MagicMock(), str(uuid.uuid4()), uuid.uuid4())

        self.assertIsNone(secret)


class CalWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_webhook_reserves_and_schedules_workflow(self) -> None:
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
        workflow = _workflow(node_id, credential_id)
        request = _make_request(
            body,
            {
                "authorization": "Bearer must-not-be-forwarded",
                "content-type": "application/json",
                "x-cal-webhook-version": "2021-10-20",
                "x-cal-signature-256": _make_signature(secret, body),
                "x-private-header": "must-not-be-forwarded",
            },
        )
        execution_id = uuid.uuid4()
        cancel_event = Event()
        db = MagicMock()

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal._get_webhook_secret", AsyncMock(return_value=secret)),
            patch(
                "app.api.cal._reserve_execution",
                AsyncMock(return_value=(execution_id, cancel_event)),
            ) as reserve_execution,
            patch("app.api.cal._schedule_execution") as schedule_execution,
        ):
            response = await cal_webhook(workflow.id, node_id, request)

        self.assertEqual(response, {"ok": True})
        reserve_execution.assert_awaited_once()
        reserved_inputs = reserve_execution.await_args.args[2]
        self.assertEqual(reserved_inputs["payload"], {"uid": "booking-1"})
        self.assertEqual(
            reserved_inputs["headers"],
            {
                "content-type": "application/json",
                "x-cal-webhook-version": "2021-10-20",
            },
        )
        schedule_execution.assert_called_once_with(
            workflow.id,
            node_id,
            reserved_inputs,
            execution_id,
            cancel_event,
        )

    async def test_duplicate_webhook_is_acknowledged_without_scheduling(self) -> None:
        from app.api.cal import cal_webhook

        node_id = str(uuid.uuid4())
        credential_id = str(uuid.uuid4())
        secret = "cal-webhook-secret"
        body = b'{"triggerEvent":"BOOKING_CREATED","payload":{"uid":"booking-1"}}'
        workflow = _workflow(node_id, credential_id)
        request = _make_request(
            body,
            {"x-cal-signature-256": _make_signature(secret, body)},
        )
        db = MagicMock()

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal._get_webhook_secret", AsyncMock(return_value=secret)),
            patch("app.api.cal._reserve_execution", AsyncMock(return_value=None)),
            patch("app.api.cal._schedule_execution") as schedule_execution,
        ):
            response = await cal_webhook(workflow.id, node_id, request)

        self.assertEqual(response, {"ok": True})
        schedule_execution.assert_not_called()

    async def test_invalid_signature_is_rejected(self) -> None:
        from app.api.cal import cal_webhook

        node_id = str(uuid.uuid4())
        workflow = _workflow(node_id, str(uuid.uuid4()))
        request = _make_request(
            b'{"triggerEvent":"BOOKING_CREATED"}',
            {"x-cal-signature-256": "invalid"},
        )
        db = MagicMock()

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal._get_webhook_secret", AsyncMock(return_value="secret")),
        ):
            with self.assertRaises(HTTPException) as context:
                await cal_webhook(workflow.id, node_id, request)

        self.assertEqual(context.exception.status_code, 403)

    async def test_missing_credential_fails_closed(self) -> None:
        from app.api.cal import cal_webhook

        node_id = str(uuid.uuid4())
        workflow = _workflow(node_id, "")
        request = _make_request(b"{}", {})
        db = MagicMock()

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                await cal_webhook(workflow.id, node_id, request)

        self.assertEqual(context.exception.status_code, 400)


class CalExecutionReservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_reservation_does_not_register_execution(self) -> None:
        from app.api.cal import _reserve_execution

        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
        workflow = _workflow("cal-node", str(uuid.uuid4()))

        with patch("app.api.cal.register_execution") as register_execution:
            reservation = await _reserve_execution(
                db,
                workflow,
                {"event": {}, "trigger_node_id": "cal-node"},
                "digest",
            )

        self.assertIsNone(reservation)
        register_execution.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_payload_without_identity_is_reserved_without_deduplication(self) -> None:
        from app.api.cal import _reserve_execution

        db = AsyncMock()
        workflow = _workflow("cal-node", str(uuid.uuid4()))
        cancel_event = Event()
        with (
            patch("app.api.cal.register_execution", return_value=cancel_event),
            patch("app.api.cal.persist_registered_execution", AsyncMock()) as persist,
        ):
            reservation = await _reserve_execution(
                db,
                workflow,
                {"event": {}, "trigger_node_id": "cal-node"},
                None,
            )

        self.assertIsNotNone(reservation)
        db.execute.assert_awaited_once()
        history_statement = db.execute.await_args.args[0]
        self.assertEqual(history_statement.compile().params["status"], "running")
        persist.assert_awaited_once()
        db.commit.assert_awaited_once()


class CalWorkflowLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_inactive_trigger_is_not_found(self) -> None:
        from app.api.cal import _find_workflow_trigger

        workflow = _workflow("cal-node", str(uuid.uuid4()))
        workflow.nodes[0]["data"]["active"] = False
        result = MagicMock()
        result.scalar_one_or_none.return_value = workflow
        db = AsyncMock()
        db.execute.return_value = result

        match = await _find_workflow_trigger(db, workflow.id, "cal-node")

        self.assertIsNone(match)

    async def test_legacy_lookup_uses_signature_to_disambiguate_cloned_node_ids(self) -> None:
        from app.api.cal import _resolve_legacy_workflow_id

        node_id = "shared-cal-node"
        first = _workflow(node_id, str(uuid.uuid4()))
        second = _workflow(node_id, str(uuid.uuid4()))
        result = MagicMock()
        result.scalars.return_value.all.return_value = [first, second]
        db = AsyncMock()
        db.execute.return_value = result
        raw_body = b'{"triggerEvent":"BOOKING_CREATED"}'

        with patch(
            "app.api.cal._get_webhook_secret",
            AsyncMock(side_effect=["wrong-secret", "matching-secret"]),
        ):
            workflow_id = await _resolve_legacy_workflow_id(
                db,
                node_id,
                raw_body,
                _make_signature("matching-secret", raw_body),
            )

        self.assertEqual(workflow_id, second.id)

    async def test_legacy_lookup_rejects_ambiguous_shared_secret(self) -> None:
        from app.api.cal import _resolve_legacy_workflow_id

        node_id = "shared-cal-node"
        first = _workflow(node_id, str(uuid.uuid4()))
        second = _workflow(node_id, str(uuid.uuid4()))
        result = MagicMock()
        result.scalars.return_value.all.return_value = [first, second]
        db = AsyncMock()
        db.execute.return_value = result
        raw_body = b'{"triggerEvent":"BOOKING_CREATED"}'

        with (
            patch(
                "app.api.cal._get_webhook_secret",
                AsyncMock(return_value="shared-secret"),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await _resolve_legacy_workflow_id(
                db,
                node_id,
                raw_body,
                _make_signature("shared-secret", raw_body),
            )

        self.assertEqual(raised.exception.status_code, 409)


class CalBackgroundExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_execution_uses_thread_and_updates_reserved_history(self) -> None:
        from app.api.cal import _execute_workflow_background

        node_id = "cal-node"
        workflow = _workflow(node_id, str(uuid.uuid4()))
        execution_id = uuid.uuid4()
        cancel_event = Event()
        inputs = {
            "triggered_by": "Cal.com",
            "trigger_node_id": node_id,
            "event": {"triggerEvent": "BOOKING_CREATED"},
            "payload": {},
        }
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=12.3,
            node_results=[],
            sub_workflow_executions=[],
        )
        db = AsyncMock()
        db.add = MagicMock()

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.cal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.cal.get_global_variables_context", AsyncMock(return_value={})),
            patch(
                "app.api.cal.asyncio.to_thread",
                AsyncMock(return_value=execution_result),
            ) as to_thread,
            patch("app.api.cal.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.cal._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.cal.clear_execution") as clear_execution,
        ):
            await _execute_workflow_background(
                workflow.id,
                node_id,
                inputs,
                execution_id,
                cancel_event,
            )

        to_thread.assert_awaited_once()
        self.assertEqual(to_thread.await_args.kwargs["timeout_seconds"], 30)
        history_statement = db.execute.await_args.args[0]
        self.assertIn("ON CONFLICT", str(history_statement))
        db.commit.assert_awaited_once()
        clear_execution.assert_called_once_with(execution_id)

    async def test_pending_execution_uses_existing_history_and_persists_resume_request(
        self,
    ) -> None:
        from app.api.cal import _execute_workflow_background

        node_id = "cal-node"
        workflow = _workflow(node_id, str(uuid.uuid4()))
        execution_id = uuid.uuid4()
        history_entry = MagicMock()
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="pending",
            outputs={"review": {}},
            execution_time_ms=5.0,
            node_results=[],
            pending_review={"summary": "Review"},
            resume_snapshot={"paused_node_id": "agent", "paused_node_label": "review"},
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=history_entry)

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.cal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.cal.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.cal.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.cal.persist_pending_hitl_execution", AsyncMock()) as persist_pending,
            patch("app.api.cal.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.cal.clear_execution") as clear_execution,
        ):
            await _execute_workflow_background(
                workflow.id,
                node_id,
                {"event": {}},
                execution_id,
                Event(),
            )

        self.assertIs(persist_pending.await_args.kwargs["history_entry"], history_entry)
        self.assertEqual(persist_pending.await_args.kwargs["trigger_source"], "Cal.com")
        db.commit.assert_awaited_once()
        clear_execution.assert_called_once_with(execution_id)

    async def test_executor_cancellation_is_persisted_as_cancelled(self) -> None:
        from app.api.cal import _execute_workflow_background
        from app.services.workflow_executor import WorkflowCancelledError

        workflow = _workflow("cal-node", str(uuid.uuid4()))
        execution_id = uuid.uuid4()
        db = AsyncMock()
        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.cal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.cal.get_global_variables_context", AsyncMock(return_value={})),
            patch(
                "app.api.cal.asyncio.to_thread",
                AsyncMock(side_effect=WorkflowCancelledError("cancelled")),
            ),
            patch(
                "app.api.cal._persist_terminal_execution",
                AsyncMock(return_value=True),
            ) as persist_terminal,
            patch("app.api.cal.clear_execution"),
        ):
            await _execute_workflow_background(
                workflow.id,
                "cal-node",
                {"event": {}},
                execution_id,
                Event(),
            )

        self.assertEqual(persist_terminal.await_args.kwargs["terminal_status"], "cancelled")
        self.assertIsNone(persist_terminal.await_args.kwargs["error_message"])

    async def test_background_failure_is_persisted_before_execution_is_cleared(self) -> None:
        from app.api.cal import _execute_workflow_background

        node_id = "cal-node"
        workflow = _workflow(node_id, str(uuid.uuid4()))
        execution_id = uuid.uuid4()
        db = AsyncMock()

        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.cal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.cal.get_global_variables_context", AsyncMock(return_value={})),
            patch(
                "app.api.cal.asyncio.to_thread",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch(
                "app.api.cal._persist_terminal_execution",
                AsyncMock(return_value=True),
            ) as persist_terminal,
            patch("app.api.cal.clear_execution") as clear_execution,
        ):
            await _execute_workflow_background(
                workflow.id,
                node_id,
                {"event": {}},
                execution_id,
                Event(),
            )

        persist_terminal.assert_awaited_once()
        self.assertEqual(persist_terminal.await_args.kwargs["terminal_status"], "error")
        clear_execution.assert_called_once_with(execution_id)

    async def test_cancellation_waits_for_worker_thread_before_returning(self) -> None:
        from app.api.cal import _execute_workflow_background

        node_id = "cal-node"
        workflow = _workflow(node_id, str(uuid.uuid4()))
        execution_id = uuid.uuid4()
        cancel_event = Event()
        started = asyncio.Event()
        release = asyncio.Event()
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="cancelled",
            outputs={},
            execution_time_ms=1.0,
            node_results=[],
            sub_workflow_executions=[],
        )

        async def blocked_execution(*_args: object, **_kwargs: object) -> ExecutionResult:
            started.set()
            await release.wait()
            return execution_result

        db = AsyncMock()
        with (
            patch("app.api.cal.async_session_maker", return_value=_session_context(db)),
            patch(
                "app.api.cal._find_workflow_trigger",
                AsyncMock(return_value=(workflow, workflow.nodes[0])),
            ),
            patch("app.api.cal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.cal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.cal.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.cal.asyncio.to_thread", side_effect=blocked_execution),
            patch("app.api.cal.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.cal._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.cal.clear_execution"),
        ):
            task = asyncio.create_task(
                _execute_workflow_background(
                    workflow.id,
                    node_id,
                    {"event": {}},
                    execution_id,
                    cancel_event,
                )
            )
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            self.assertTrue(cancel_event.is_set())
            self.assertFalse(task.done())
            release.set()
            await task


class CalBackgroundShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_sets_cancel_events_and_awaits_tasks(self) -> None:
        from app.api.cal import (
            _BACKGROUND_CANCEL_EVENTS,
            _BACKGROUND_TASKS,
            _schedule_execution,
            shutdown_background_tasks,
        )

        cancel_event = Event()

        async def wait_for_cancel(
            _workflow_id: uuid.UUID,
            _node_id: str,
            _inputs: dict[str, object],
            _execution_id: uuid.UUID,
            event: Event,
        ) -> None:
            while not event.is_set():
                await asyncio.sleep(0)

        with patch("app.api.cal._execute_workflow_background", side_effect=wait_for_cancel):
            _schedule_execution(uuid.uuid4(), "node", {}, uuid.uuid4(), cancel_event)
            await asyncio.sleep(0)
            await shutdown_background_tasks()

        self.assertTrue(cancel_event.is_set())
        self.assertFalse(_BACKGROUND_TASKS)
        self.assertFalse(_BACKGROUND_CANCEL_EVENTS)

    async def test_shutdown_returns_after_bounded_wait(self) -> None:
        from app.api.cal import (
            _BACKGROUND_CANCEL_EVENTS,
            _BACKGROUND_TASKS,
            _schedule_execution,
            shutdown_background_tasks,
        )

        release = asyncio.Event()
        cancel_event = Event()

        async def ignore_cooperative_cancel(
            _workflow_id: uuid.UUID,
            _node_id: str,
            _inputs: dict[str, object],
            _execution_id: uuid.UUID,
            _event: Event,
        ) -> None:
            await release.wait()

        with (
            patch(
                "app.api.cal._execute_workflow_background", side_effect=ignore_cooperative_cancel
            ),
            patch("app.api.cal._BACKGROUND_SHUTDOWN_TIMEOUT_SECONDS", 0.01),
        ):
            _schedule_execution(uuid.uuid4(), "node", {}, uuid.uuid4(), cancel_event)
            await asyncio.sleep(0)
            await asyncio.wait_for(shutdown_background_tasks(), timeout=0.5)

        self.assertTrue(cancel_event.is_set())
        self.assertTrue(_BACKGROUND_TASKS)
        release.set()
        await asyncio.gather(*list(_BACKGROUND_TASKS))
        self.assertFalse(_BACKGROUND_TASKS)
        self.assertFalse(_BACKGROUND_CANCEL_EVENTS)


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
