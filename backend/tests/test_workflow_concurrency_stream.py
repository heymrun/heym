"""A held run's SSE stream: queued updates, then started, then the result."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

from app.services import queued_run_stream
from app.services.workflow_concurrency import Admission, QueueInfo


def _frames(chunks: list[str]) -> list[dict]:
    return [json.loads(c[len("data: ") :]) for c in chunks if c.startswith("data: ")]


class QueuedRunStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_then_started_then_complete(self) -> None:
        workflow_id, execution_id = uuid.uuid4(), uuid.uuid4()
        queue_two = {"position": 2, "size": 2, "running": 1, "limit": 1}
        queue_one = {"position": 1, "size": 1, "running": 1, "limit": 1}
        bodies = [
            {"status": "queued", "queue": queue_two},
            {"status": "queued", "queue": queue_two},
            {"status": "queued", "queue": queue_one},
            {"status": "running", "queue": None},
            {"status": "success", "queue": None, "outputs": {"a": 1}, "execution_time_ms": 9.0},
        ]
        with (
            patch.object(
                queued_run_stream.workflow_concurrency,
                "build_status_body",
                AsyncMock(side_effect=bodies),
            ),
            patch.object(queued_run_stream, "POLL_SECONDS", 0),
        ):
            chunks = [
                c
                async for c in queued_run_stream.queued_run_events(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    is_disconnected=AsyncMock(return_value=False),
                )
            ]
        frames = _frames(chunks)
        self.assertEqual(
            [f["type"] for f in frames],
            ["queued", "queued", "execution_started", "execution_complete"],
        )
        self.assertEqual(frames[1]["position"], 1)
        self.assertEqual(frames[-1]["outputs"], {"a": 1})
        self.assertEqual(frames[-1]["execution_history_id"], str(execution_id))
        self.assertEqual(frames[-1]["node_results"], [])

    async def test_a_disconnect_stops_watching_without_cancelling(self) -> None:
        queued = {"status": "queued", "queue": {"position": 1, "size": 1, "running": 1, "limit": 1}}
        with patch.object(
            queued_run_stream.workflow_concurrency,
            "build_status_body",
            AsyncMock(return_value=queued),
        ):
            chunks = [
                c
                async for c in queued_run_stream.queued_run_events(
                    workflow_id=uuid.uuid4(),
                    execution_id=uuid.uuid4(),
                    is_disconnected=AsyncMock(return_value=True),
                )
            ]
        self.assertEqual([f["type"] for f in _frames(chunks)], ["queued"])

    async def test_simple_response_sends_only_outputs_at_the_end(self) -> None:
        done = {"status": "success", "queue": None, "outputs": {"a": 1}, "execution_time_ms": 1.0}
        with (
            patch.object(
                queued_run_stream.workflow_concurrency,
                "build_status_body",
                AsyncMock(return_value=done),
            ),
            patch.object(queued_run_stream, "POLL_SECONDS", 0),
        ):
            chunks = [
                c
                async for c in queued_run_stream.queued_run_events(
                    workflow_id=uuid.uuid4(),
                    execution_id=uuid.uuid4(),
                    is_disconnected=AsyncMock(return_value=False),
                    simple_response=True,
                )
            ]
        self.assertEqual(_frames(chunks)[-1], {"outputs": {"a": 1}})


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _stream_request() -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/workflows/test/execute/stream",
            "headers": [(b"x-simple-response", b"false")],
            "query_string": b"",
        },
        receive,
    )


class StreamEndpointQueuedTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_held_run_gets_the_queued_stream_and_never_executes_here(self) -> None:
        from app.api.workflows import execute_workflow_stream

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="wf",
            nodes=[{"id": "n1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            sse_enabled=True,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_node_config={},
            workflow_timeout_seconds=None,
            concurrency_limit=1,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        admission = Admission(kind="queued", execution_id=uuid.uuid4(), queue=QueueInfo(1, 1, 1, 1))

        async def fake_events(**_kwargs: object):
            yield 'data: {"type": "queued"}\n\n'

        register = MagicMock()
        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", register),
            patch(
                "app.api.workflows.workflow_concurrency.admit",
                AsyncMock(return_value=admission),
            ),
            patch("app.api.workflows.queued_run_events", fake_events),
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id, request=_stream_request(), current_user=None, db=db
            )
            chunks = [chunk async for chunk in response.body_iterator]
        self.assertEqual(chunks, ['data: {"type": "queued"}\n\n'])
        register.assert_not_called()
