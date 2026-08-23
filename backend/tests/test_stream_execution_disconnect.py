"""A streamed run must be recorded even when its client stops reading.

Starlette cancels the SSE response task on `http.disconnect`, so a run recorded by the
generator that feeds the browser would complete on the server and leave no history row.
"""

import asyncio
import unittest
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.workflows import execute_workflow_stream
from app.db.models import ExecutionHistory


class _FakeRequest:
    def __init__(self) -> None:
        self.method = "POST"
        self.headers: dict[str, str] = {"x-simple-response": "false"}
        self.query_params: dict[str, str] = {"trigger_source": "Canvas"}

    async def is_disconnected(self) -> bool:
        return False


class StreamedRunSurvivesClientDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_run_is_recorded_after_the_client_stops_reading(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="wait",
            nodes=[{"id": "n1", "type": "wait", "data": {"duration": 10}}],
            edges=[],
            http_method="POST",
            sse_enabled=False,
            sse_node_config={},
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            workflow_timeout_seconds=None,
        )
        request_db = AsyncMock()
        request_db.execute = AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)
        )
        run_session = AsyncMock()
        run_session.add = MagicMock()
        run_session.get = AsyncMock(return_value=workflow)

        @asynccontextmanager
        async def fake_session_maker():
            yield run_session

        def fake_streaming_run(**kwargs):
            yield {"type": "node_start", "node_id": "n1"}
            yield {
                "type": "execution_complete",
                "workflow_id": str(workflow.id),
                "status": "success",
                "outputs": {"done": True},
                "execution_time_ms": 10,
                "node_results": [{"node_id": "n1", "status": "success"}],
                "sub_workflow_executions": [],
            }

        with (
            patch(
                "app.api.workflows.parse_execute_body",
                AsyncMock(return_value=({}, False, "Canvas", False)),
            ),
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.get_client_ip", return_value="127.0.0.1"),
            patch(
                "app.api.workflows.file_intake_service.find_file_upload_trigger",
                return_value=None,
            ),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.build_public_base_url", return_value="http://testserver"),
            patch("app.api.workflows.execute_workflow_streaming", fake_streaming_run),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.async_session_maker", fake_session_maker),
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id,
                request=_FakeRequest(),
                current_user=SimpleNamespace(id=workflow.owner_id),
                db=request_db,
            )

            # The browser reads the opening event and then goes away mid-run.
            first_event = await response.body_iterator.__anext__()
            self.assertIn("execution_started", first_event)
            await response.body_iterator.aclose()

            for _ in range(200):
                if run_session.add.call_count:
                    break
                await asyncio.sleep(0.01)

        run_session.add.assert_called_once()
        entry = run_session.add.call_args.args[0]
        self.assertIsInstance(entry, ExecutionHistory)
        self.assertEqual(entry.status, "success")
        self.assertEqual(entry.outputs, {"done": True})
        run_session.commit.assert_awaited()
