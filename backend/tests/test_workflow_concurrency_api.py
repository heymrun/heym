"""The webhook answers 202 with a status URL when the limit is full, and 429 when the queue is."""

import json
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from app.api.workflows import execute_workflow_endpoint
from app.db.models import WorkflowAuthType
from app.services.workflow_concurrency import Admission, QueueInfo
from app.services.workflow_executor import ExecutionResult


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _request(query: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("heym.example", 443),
            "path": "/api/workflows/x/execute",
            "headers": [(b"host", b"heym.example")],
            "query_string": query,
        },
        receive,
    )


def _success() -> ExecutionResult:
    return ExecutionResult(
        workflow_id=uuid.uuid4(),
        status="success",
        outputs={},
        node_results=[],
        execution_time_ms=1.0,
    )


class ExecuteEndpointConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def _workflow(self, *, anonymous: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="wf",
            nodes=[{"id": "o", "type": "output", "data": {"label": "o", "message": "ok"}}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            http_method="POST",
            auth_type=WorkflowAuthType.anonymous if anonymous else WorkflowAuthType.jwt,
            concurrency_limit=1,
            workflow_timeout_seconds=None,
        )

    async def _call(
        self,
        workflow: SimpleNamespace,
        dispatch_result: object,
        *,
        query: bytes = b"",
        session_user: SimpleNamespace | None = None,
        has_access: bool = True,
    ) -> tuple[object, AsyncMock]:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        dispatch = AsyncMock(return_value=dispatch_result)
        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=session_user)),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=has_access)),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.dispatch_workflow", dispatch),
            patch(
                "app.api.workflows.ExecutionHistory",
                side_effect=lambda **kw: SimpleNamespace(id=uuid.uuid4()),
            ),
        ):
            response = await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=_request(query),
                current_user=session_user,
                db=db,
            )
        return response, dispatch

    async def test_a_queued_run_answers_202_with_location_and_queue(self) -> None:
        workflow = self._workflow()
        execution_id = uuid.uuid4()
        admission = Admission(kind="queued", execution_id=execution_id, queue=QueueInfo(2, 5, 1, 1))
        response, dispatch = await self._call(workflow, admission)
        self.assertEqual(response.status_code, 202)
        body = json.loads(response.body)
        self.assertEqual(body["queue"], {"position": 2, "size": 5, "running": 1, "limit": 1})
        self.assertEqual(response.headers["location"], body["status_url"])
        self.assertTrue(
            body["status_url"].endswith(
                f"/api/workflows/{workflow.id}/executions/{execution_id}/status"
            )
        )
        self.assertEqual(dispatch.await_args.kwargs["on_queued"], "return")
        self.assertEqual(dispatch.await_args.kwargs["concurrency_limit"], 1)

    async def test_only_anonymous_workflows_mint_a_status_token(self) -> None:
        queued = Admission(
            kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1), status_token="t"
        )
        _, dispatch = await self._call(self._workflow(anonymous=True), queued)
        self.assertTrue(dispatch.await_args.kwargs["mint_status_token"])
        _, dispatch = await self._call(self._workflow(), queued)
        self.assertFalse(dispatch.await_args.kwargs["mint_status_token"])

    async def test_a_full_queue_is_429(self) -> None:
        full = Admission(kind="queue_full", execution_id=uuid.uuid4(), queue=QueueInfo(0, 3, 1, 1))
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._workflow(), full)
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_an_editor_test_run_is_exempt(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        _, dispatch = await self._call(
            self._workflow(), _success(), query=b"test_run=true", session_user=user
        )
        self.assertTrue(dispatch.await_args.kwargs["concurrency_exempt"])

    async def test_test_run_without_a_session_is_gated(self) -> None:
        _, dispatch = await self._call(
            self._workflow(), _success(), query=b"test_run=true", session_user=None
        )
        self.assertFalse(dispatch.await_args.kwargs["concurrency_exempt"])

    async def test_a_session_without_access_is_gated(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        _, dispatch = await self._call(
            self._workflow(),
            _success(),
            query=b"test_run=true",
            session_user=user,
            has_access=False,
        )
        self.assertFalse(dispatch.await_args.kwargs["concurrency_exempt"])
