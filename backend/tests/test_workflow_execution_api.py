import json
import os
import subprocess
import sys
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

from app.api.ai_assistant import run_execute_workflow_tool
from app.api.mcp import get_credentials_context_for_user
from app.api.portal import portal_cancel_execution, portal_execute_stream
from app.api.workflows import (
    collect_referenced_workflows,
    execute_workflow_endpoint,
    execute_workflow_stream,
    get_credentials_context,
    parse_execute_body,
)
from app.db.models import Credential, CredentialType, DataTable, DataTableRow
from app.models.schemas import PortalExecuteRequest
from app.services.workflow_executor import (
    ExecutionResult,
    SubWorkflowExecution,
    WorkflowCancelledError,
    WorkflowExecutor,
)


def make_request(
    *,
    body: bytes = b"",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/workflows/test/execute/stream",
        "headers": headers or [],
        "query_string": query_string,
    }
    return Request(scope, receive)


class CollectReferencedWorkflowsAccessTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _result(value: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    async def test_execute_node_rejects_referenced_workflow_without_actor_access(self) -> None:
        actor_id = uuid.uuid4()
        victim_workflow_id = uuid.uuid4()
        victim_workflow = SimpleNamespace(
            id=victim_workflow_id,
            owner_id=uuid.uuid4(),
            name="victim",
            nodes=[{"id": "start", "type": "manual", "data": {}}],
            edges=[],
        )
        db = AsyncMock()
        db.execute.side_effect = [
            self._result(victim_workflow),
            self._result(None),
            self._result(None),
        ]

        with self.assertRaises(HTTPException) as ctx:
            await collect_referenced_workflows(
                db,
                [
                    {
                        "id": "execute-1",
                        "type": "execute",
                        "data": {"executeWorkflowId": str(victim_workflow_id)},
                    }
                ],
                actor_user_id=actor_id,
            )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Referenced workflow access denied")

    async def test_agent_subworkflow_rejects_referenced_workflow_without_actor_access(self) -> None:
        actor_id = uuid.uuid4()
        victim_workflow_id = uuid.uuid4()
        victim_workflow = SimpleNamespace(
            id=victim_workflow_id,
            owner_id=uuid.uuid4(),
            name="victim",
            nodes=[{"id": "start", "type": "manual", "data": {}}],
            edges=[],
        )
        db = AsyncMock()
        db.execute.side_effect = [
            self._result(victim_workflow),
            self._result(None),
            self._result(None),
        ]

        with self.assertRaises(HTTPException) as ctx:
            await collect_referenced_workflows(
                db,
                [
                    {
                        "id": "agent-1",
                        "type": "agent",
                        "data": {"subWorkflowIds": [str(victim_workflow_id)]},
                    }
                ],
                actor_user_id=actor_id,
            )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Referenced workflow access denied")

    async def test_actor_owned_referenced_workflow_is_cached(self) -> None:
        actor_id = uuid.uuid4()
        target_workflow_id = uuid.uuid4()
        target_workflow = SimpleNamespace(
            id=target_workflow_id,
            owner_id=actor_id,
            name="owned child",
            nodes=[{"id": "start", "type": "manual", "data": {}}],
            edges=[],
        )
        db = AsyncMock()
        db.execute.return_value = self._result(target_workflow)

        cache = await collect_referenced_workflows(
            db,
            [
                {
                    "id": "execute-1",
                    "type": "execute",
                    "data": {"executeWorkflowId": str(target_workflow_id)},
                }
            ],
            actor_user_id=actor_id,
        )

        self.assertIn(str(target_workflow_id), cache)
        self.assertEqual(cache[str(target_workflow_id)]["name"], "owned child")
        self.assertEqual(cache[str(target_workflow_id)]["nodes"], target_workflow.nodes)


class ParseExecuteBodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_trigger_source_from_query_string_for_generic_body(self) -> None:
        request = make_request(
            body=json.dumps({"city": "ankara"}).encode("utf-8"),
            query_string=b"trigger_source=Quick+Drawer&test_run=true",
        )

        raw_body, test_run, trigger_source, _ = await parse_execute_body(request)

        self.assertEqual(raw_body, {"city": "ankara"})
        self.assertTrue(test_run)
        self.assertEqual(trigger_source, "Quick Drawer")

    async def test_body_trigger_source_overrides_query_for_legacy_payload(self) -> None:
        request = make_request(
            body=json.dumps(
                {
                    "inputs": {"city": "ankara"},
                    "test_run": False,
                    "trigger_source": "Quick Drawer",
                }
            ).encode("utf-8"),
            query_string=b"trigger_source=Canvas&test_run=true",
        )

        raw_body, test_run, trigger_source, _ = await parse_execute_body(request)

        self.assertEqual(raw_body, {"city": "ankara"})
        self.assertFalse(test_run)
        self.assertEqual(trigger_source, "Quick Drawer")

    async def test_defaults_to_api_when_no_trigger_source_provided(self) -> None:
        request = make_request(body=json.dumps({"city": "ankara"}).encode("utf-8"))

        _, _, trigger_source, _ = await parse_execute_body(request)

        self.assertEqual(trigger_source, "API")

    async def test_defaults_to_api_for_empty_body(self) -> None:
        request = make_request()

        _, _, trigger_source, _ = await parse_execute_body(request)

        self.assertEqual(trigger_source, "API")

    async def test_header_trigger_source_overrides_api_default(self) -> None:
        request = make_request(
            headers=[(b"x-trigger-source", b"MyApp")],
        )

        _, _, trigger_source, _ = await parse_execute_body(request)

        self.assertEqual(trigger_source, "MyApp")


class WorkflowExecutorTerminateSubprocessTests(unittest.TestCase):
    def test_terminate_subprocess_stops_running_process(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        popen_kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            **popen_kwargs,
        )
        self.addCleanup(self._cleanup_process, process)

        executor._terminate_subprocess(process)

        self.assertIsNotNone(process.wait(timeout=5))

    @staticmethod
    def _cleanup_process(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.kill()
        process.wait(timeout=5)


class RunExecuteWorkflowToolCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_cancelled_when_event_is_already_set(self) -> None:
        cancel_event = Event()
        cancel_event.set()

        result = await run_execute_workflow_tool(
            db=AsyncMock(),
            user_id=uuid.uuid4(),
            workflow_id_str=str(uuid.uuid4()),
            inputs={},
            public_base_url="http://localhost",
            cancel_event=cancel_event,
        )

        self.assertEqual(
            json.loads(result),
            {"status": "cancelled", "error": "Execution cancelled"},
        )


class RunExecuteWorkflowToolActorForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_actor_user_id_to_execute_workflow(self) -> None:
        user_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Demo",
            nodes=[{"id": "n1", "type": "input"}],
            edges=[],
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={},
            execution_time_ms=1.0,
        )

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch(
                "app.api.ai_assistant.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.ai_assistant.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.api.ai_assistant.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.api.ai_assistant.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.api.ai_assistant.execute_workflow",
                MagicMock(return_value=execution_result),
            ) as mock_execute,
        ):
            result = await run_execute_workflow_tool(
                db=db,
                user_id=user_id,
                workflow_id_str=str(workflow.id),
                inputs={},
                public_base_url="http://localhost",
            )

        self.assertEqual(json.loads(result)["status"], "success")
        mock_execute.assert_called_once()
        self.assertEqual(mock_execute.call_args.kwargs["actor_user_id"], user_id)


class PortalCancelExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_cancel_requested_when_active_execution_exists(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarResult(SimpleNamespace(id=workflow_id)),
                _ScalarResult(None),
            ]
        )

        with (
            patch("app.api.portal.cancel_active_execution", return_value=True) as cancel_mock,
            patch(
                "app.api.portal.request_persisted_execution_cancel",
                AsyncMock(return_value=True),
            ) as persisted_cancel_mock,
        ):
            result = await portal_cancel_execution(
                slug="portal-test",
                execution_id=execution_id,
                request=make_request(),
                db=db,
            )

        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_mock.assert_called_once_with(workflow_id=workflow_id, execution_id=execution_id)
        persisted_cancel_mock.assert_awaited_once_with(
            db,
            workflow_id=workflow_id,
            execution_id=execution_id,
        )

    async def test_returns_cancel_requested_when_execution_is_on_another_worker(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarResult(SimpleNamespace(id=workflow_id)),
                _ScalarResult(None),
            ]
        )

        with (
            patch("app.api.portal.cancel_active_execution", return_value=False),
            patch(
                "app.api.portal.request_persisted_execution_cancel",
                AsyncMock(return_value=True),
            ),
        ):
            result = await portal_cancel_execution(
                slug="portal-test",
                execution_id=execution_id,
                request=make_request(),
                db=db,
            )

        self.assertEqual(result, {"status": "cancel_requested"})

    async def test_raises_not_found_when_execution_is_missing(self) -> None:
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarResult(SimpleNamespace(id=workflow_id)),
                _ScalarResult(None),
            ]
        )

        with (
            patch("app.api.portal.cancel_active_execution", return_value=False),
            patch(
                "app.api.portal.request_persisted_execution_cancel",
                AsyncMock(return_value=False),
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                await portal_cancel_execution(
                    slug="portal-test",
                    execution_id=execution_id,
                    request=make_request(),
                    db=db,
                )

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.detail, "Execution not found or already finished")


class PortalExecuteStreamHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_hidden_heartbeat_while_waiting_for_workflow_events(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Portal Workflow",
            nodes=[{"id": "n1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
        )
        release_executor = Event()

        def fake_streaming_executor(**_kwargs: object):
            release_executor.wait(timeout=2)
            yield {
                "type": "execution_complete",
                "workflow_id": str(workflow.id),
                "status": "success",
                "outputs": {},
                "node_results": [],
                "sub_workflow_executions": [],
                "execution_time_ms": 0,
            }

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarResult(workflow),
                _ScalarResult(None),
            ]
        )
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.portal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.portal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.portal.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.portal.register_execution", return_value=Event()),
            patch("app.api.portal.clear_active_execution"),
            patch("app.api.portal.execute_workflow_streaming", fake_streaming_executor),
            patch("app.api.portal._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.portal.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.portal.PORTAL_SSE_HEARTBEAT_SECONDS", 0.001),
        ):
            response = await portal_execute_stream(
                slug="portal-test",
                execute_data=PortalExecuteRequest(inputs={}),
                request=make_request(),
                db=db,
            )

            stream = response.body_iterator
            self.assertIn('"type": "execution_started"', await stream.__anext__())
            self.assertEqual(await stream.__anext__(), ": heartbeat\n\n")

            release_executor.set()
            complete_chunk = ""
            for _ in range(100):
                chunk = await stream.__anext__()
                if '"type": "execution_complete"' in chunk:
                    complete_chunk = chunk
                    break
                self.assertEqual(chunk, ": heartbeat\n\n")

            self.assertIn('"type": "execution_complete"', complete_chunk)
            with self.assertRaises(StopAsyncIteration):
                await stream.__anext__()


class ExecuteWorkflowStreamHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_hidden_heartbeat_while_waiting_for_workflow_events(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Canvas Workflow",
            nodes=[{"id": "n1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            sse_enabled=True,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_node_config={},
            workflow_timeout_seconds=None,
        )
        release_executor = Event()

        def fake_streaming_executor(**_kwargs: object):
            release_executor.wait(timeout=2)
            yield {
                "type": "execution_complete",
                "workflow_id": str(workflow.id),
                "status": "success",
                "outputs": {},
                "node_results": [],
                "sub_workflow_executions": [],
                "execution_time_ms": 0,
            }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.execute_workflow_streaming", fake_streaming_executor),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.WORKFLOW_SSE_HEARTBEAT_SECONDS", 0.001),
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id,
                request=make_request(
                    query_string=b"trigger_source=Canvas",
                    headers=[(b"x-simple-response", b"false")],
                ),
                current_user=None,
                db=db,
            )

            stream = response.body_iterator
            self.assertIn('"type": "execution_started"', await stream.__anext__())
            self.assertEqual(await stream.__anext__(), ": heartbeat\n\n")

            release_executor.set()
            complete_chunk = ""
            for _ in range(100):
                chunk = await stream.__anext__()
                if '"type": "execution_complete"' in chunk:
                    complete_chunk = chunk
                    break
                self.assertEqual(chunk, ": heartbeat\n\n")

            self.assertIn('"type": "execution_complete"', complete_chunk)
            with self.assertRaises(StopAsyncIteration):
                await stream.__anext__()


class ExecuteWorkflowStreamAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_external_sse_request_when_workflow_sse_disabled(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            sse_enabled=False,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        with patch("app.api.workflows.validate_workflow_auth", AsyncMock()):
            with self.assertRaises(HTTPException) as context:
                await execute_workflow_stream(
                    workflow_id=workflow.id,
                    request=make_request(),
                    current_user=None,
                    db=db,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "SSE streaming is disabled for this workflow")

    async def test_allows_quick_drawer_stream_when_workflow_sse_disabled(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            sse_enabled=False,
            nodes=[{"id": "node-1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        request = make_request(query_string=b"trigger_source=Quick+Drawer")

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id,
                request=request,
                current_user=None,
                db=db,
            )

        self.assertEqual(response.media_type, "text/event-stream")

    async def test_allows_canvas_stream_when_workflow_sse_disabled(self) -> None:
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            sse_enabled=False,
            nodes=[{"id": "node-1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        request = make_request(query_string=b"trigger_source=Canvas")

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
        ):
            response = await execute_workflow_stream(
                workflow_id=workflow.id,
                request=request,
                current_user=None,
                db=db,
            )

        self.assertEqual(response.media_type, "text/event-stream")


class WorkflowExecutorUpstreamNodeTests(unittest.TestCase):
    """Tests for WorkflowExecutor.get_upstream_node_ids / get_upstream_node_labels."""

    def _make_node(self, node_id: str, label: str, node_type: str = "set") -> dict:
        return {"id": node_id, "type": node_type, "data": {"label": label}}

    def _make_edge(self, source: str, target: str) -> dict:
        return {"id": f"{source}-{target}", "source": source, "target": target}

    def test_linear_chain_returns_all_ancestors(self) -> None:
        """A → B → C → D: upstream of D is {A, B, C}."""
        nodes = [
            self._make_node("a", "userInput", "textInput"),
            self._make_node("b", "waitTenSeconds", "wait"),
            self._make_node("c", "addTimestamp", "set"),
            self._make_node("d", "finalOutput", "output"),
        ]
        edges = [
            self._make_edge("a", "b"),
            self._make_edge("b", "c"),
            self._make_edge("c", "d"),
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        upstream = executor.get_upstream_node_ids("d")

        self.assertEqual(upstream, {"a", "b", "c"})

    def test_direct_parent_only_for_root_child(self) -> None:
        """A → B: upstream of B is only {A}."""
        nodes = [
            self._make_node("a", "trigger", "textInput"),
            self._make_node("b", "process", "set"),
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[self._make_edge("a", "b")])

        upstream = executor.get_upstream_node_ids("b")

        self.assertEqual(upstream, {"a"})

    def test_node_not_in_upstream_of_itself(self) -> None:
        """A → B: B must not be its own upstream."""
        nodes = [self._make_node("a", "A"), self._make_node("b", "B")]
        executor = WorkflowExecutor(nodes=nodes, edges=[self._make_edge("a", "b")])

        upstream = executor.get_upstream_node_ids("b")

        self.assertNotIn("b", upstream)

    def test_sibling_not_in_upstream(self) -> None:
        """A → C and B → C: upstream of B is empty; C is not upstream of B."""
        nodes = [
            self._make_node("a", "A"),
            self._make_node("b", "B"),
            self._make_node("c", "C"),
        ]
        edges = [self._make_edge("a", "c"), self._make_edge("b", "c")]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        upstream_b = executor.get_upstream_node_ids("b")

        self.assertEqual(upstream_b, set())

    def test_upstream_labels_match_node_labels(self) -> None:
        """get_upstream_node_labels returns labels, not IDs."""
        nodes = [
            self._make_node("a", "userInput", "textInput"),
            self._make_node("b", "addTimestamp", "set"),
            self._make_node("c", "finalOutput", "output"),
        ]
        edges = [self._make_edge("a", "b"), self._make_edge("b", "c")]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        labels = executor.get_upstream_node_labels("c")

        self.assertEqual(labels, {"userInput", "addTimestamp"})

    def test_upstream_labels_are_cached_per_node(self) -> None:
        nodes = [
            self._make_node("a", "userInput", "textInput"),
            self._make_node("b", "addTimestamp", "set"),
            self._make_node("c", "finalOutput", "output"),
        ]
        edges = [self._make_edge("a", "b"), self._make_edge("b", "c")]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        with patch.object(
            executor,
            "get_upstream_node_ids",
            wraps=executor.get_upstream_node_ids,
        ) as upstream_ids:
            first = executor.get_upstream_node_labels("c")
            second = executor.get_upstream_node_labels("c")

        self.assertEqual(first, {"userInput", "addTimestamp"})
        self.assertIs(first, second)
        self.assertEqual(upstream_ids.call_count, 1)

    def test_isolated_node_has_no_upstream(self) -> None:
        """A node with no incoming edges has an empty upstream set."""
        nodes = [self._make_node("solo", "Solo")]
        executor = WorkflowExecutor(nodes=nodes, edges=[])

        upstream = executor.get_upstream_node_ids("solo")

        self.assertEqual(upstream, set())


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _ScalarsResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> object:
        return SimpleNamespace(all=lambda: self._values)


class WorkflowExecutorContextSnapshotTests(unittest.TestCase):
    def test_condition_false_skips_default_true_source_handle(self) -> None:
        nodes = [
            {
                "id": "condition",
                "type": "condition",
                "data": {"label": "isValid", "condition": "$input.valid"},
            },
            {"id": "loop", "type": "loop", "data": {"label": "loop"}},
            {"id": "update", "type": "dataTable", "data": {"label": "updateRow"}},
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[])

        result = executor.execute_node("condition", {"input": {"valid": False}})
        skipped_handles = set(result.metadata.get("skip_loop_source_handles") or [])

        self.assertEqual(result.output, {"branch": "false"})
        self.assertIn("true", skipped_handles)
        self.assertTrue(
            executor._source_handle_is_skipped(
                {"source": "condition", "target": "loop"},
                skipped_handles,
            )
        )
        self.assertFalse(
            executor._source_handle_is_skipped(
                {"source": "condition", "target": "update", "sourceHandle": "false"},
                skipped_handles,
            )
        )

    def test_downstream_loop_expression_uses_source_iteration_snapshot(self) -> None:
        nodes = [
            {"id": "loop", "type": "loop", "data": {"label": "loop"}},
            {
                "id": "condition",
                "type": "condition",
                "data": {"label": "usernameRepoValid"},
            },
            {"id": "update", "type": "dataTable", "data": {"label": "updateRow"}},
        ]
        edges = [
            {
                "id": "e-loop-condition",
                "source": "loop",
                "target": "condition",
                "sourceHandle": "loop",
            },
            {
                "id": "e-condition-update",
                "source": "condition",
                "target": "update",
                "sourceHandle": "false",
            },
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        first_loop_output = {
            "item": {"id": "row-1", "data": {"targetRepo": "MoaKK/npmstats"}},
            "index": 0,
            "branch": "loop",
        }
        second_loop_output = {
            "item": {"id": "row-2", "data": {"targetRepo": "kisugez/moderator"}},
            "index": 1,
            "branch": "loop",
        }

        executor.store_node_output("loop", "loop", first_loop_output, {})
        condition_inputs = executor.get_node_inputs_for_edges("condition", edges)
        executor.store_node_output(
            "condition",
            "usernameRepoValid",
            {"branch": "false"},
            condition_inputs,
        )
        executor.store_node_output("loop", "loop", second_loop_output, {})

        update_inputs = executor.get_node_inputs_for_edges("update", edges)
        resolved_row_id = executor.resolve_expression(
            "$loop.item.id",
            update_inputs,
            "update",
            preserve_type=True,
        )

        self.assertEqual(resolved_row_id, "row-1")
        self.assertEqual(
            executor.resolve_expression(
                "$usernameRepoValid.branch",
                update_inputs,
                "update",
                preserve_type=True,
            ),
            "false",
        )


class _FakeQuery:
    def __init__(self, result: object, count_result: int = 0) -> None:
        self._result = result
        self._count_result = count_result
        self.filter_args: list[tuple[object, ...]] = []

    def filter(self, *_args: object) -> "_FakeQuery":
        self.filter_args.append(_args)
        return self

    def first(self) -> object:
        return self._result

    def join(self, *_args: object) -> "_FakeQuery":
        return self

    def all(self) -> list[object]:
        if isinstance(self._result, list):
            return self._result
        return [] if self._result is None else [self._result]

    def count(self) -> int:
        return self._count_result


class _SequenceQuery:
    def __init__(
        self, *, first_result: object = None, all_result: list[object] | None = None
    ) -> None:
        self._first_result = first_result
        self._all_result = all_result if all_result is not None else []

    def filter(self, *_args: object) -> "_SequenceQuery":
        return self

    def join(self, *_args: object) -> "_SequenceQuery":
        return self

    def first(self) -> object:
        return self._first_result

    def all(self) -> list[object]:
        return self._all_result


class _SequenceSession:
    def __init__(self, queries: list[_SequenceQuery]) -> None:
        self._queries = list(queries)

    def query(self, *_models: object) -> _SequenceQuery:
        if not self._queries:
            raise AssertionError("Unexpected query")
        return self._queries.pop(0)


class _FakeDataTableSession:
    def __init__(
        self,
        table: object,
        existing_row: object | None = None,
        count_result: int = 0,
    ) -> None:
        self.table = table
        self.existing_row = existing_row
        self.count_result = count_result
        self.added_rows: list[DataTableRow] = []
        self.commits = 0
        self.last_row_query: _FakeQuery | None = None

    def __enter__(self) -> "_FakeDataTableSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def query(self, model: object) -> _FakeQuery:
        if model is DataTable:
            return _FakeQuery(self.table)
        if model is DataTableRow:
            self.last_row_query = _FakeQuery(self.existing_row, count_result=self.count_result)
            return self.last_row_query
        return _FakeQuery(None)

    def add(self, row: DataTableRow) -> None:
        self.added_rows.append(row)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _row: DataTableRow) -> None:
        return None


class WorkflowExecutorDataTableNodeTests(unittest.TestCase):
    def test_resource_lookup_requires_actor_user_id(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        with self.assertRaisesRegex(ValueError, "actor_user_id"):
            executor._get_accessible_credential(_SequenceSession([]), uuid.uuid4())

    def test_credential_lookup_returns_none_without_actor_access(self) -> None:
        actor_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        fake_db = _SequenceSession(
            [
                _SequenceQuery(first_result=None),
                _SequenceQuery(first_result=None),
                _SequenceQuery(first_result=None),
            ]
        )
        executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=actor_id)

        credential = executor._get_accessible_credential(fake_db, credential_id)

        self.assertIsNone(credential)

    def test_credential_lookup_allows_direct_share(self) -> None:
        actor_id = uuid.uuid4()
        credential = Credential(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Shared",
            type=CredentialType.openai,
            encrypted_config="encrypted",
        )
        fake_db = _SequenceSession(
            [
                _SequenceQuery(first_result=None),
                _SequenceQuery(first_result=credential),
            ]
        )
        executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=actor_id)

        result = executor._get_accessible_credential(fake_db, credential.id)

        self.assertIs(result, credential)

    def test_shared_vector_store_uses_backing_credential_without_separate_share(self) -> None:
        actor_id = uuid.uuid4()
        credential = Credential(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Qdrant",
            type=CredentialType.qdrant,
            encrypted_config="encrypted",
        )
        store = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            credential_id=credential.id,
            collection_name="shared_collection",
        )
        fake_db = _SequenceSession(
            [
                _SequenceQuery(first_result=None),
                _SequenceQuery(first_result=store),
                _SequenceQuery(first_result=credential),
            ]
        )
        executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=actor_id)

        accessible_store = executor._get_accessible_vector_store(fake_db, store.id)
        backing_credential = executor._get_vector_store_backing_credential(
            fake_db, accessible_store.credential_id
        )

        self.assertIs(accessible_store, store)
        self.assertIs(backing_credential, credential)

    def test_data_table_lookup_rejects_write_with_read_only_team_share(self) -> None:
        actor_id = uuid.uuid4()
        table = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            columns=[],
        )
        fake_db = _SequenceSession(
            [
                _SequenceQuery(first_result=None),
                _SequenceQuery(all_result=[]),
                _SequenceQuery(all_result=[(table, "read")]),
            ]
        )
        executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=actor_id)

        with self.assertRaisesRegex(ValueError, "Write access required"):
            executor._get_accessible_data_table(fake_db, table.id, "insert")

    def test_data_table_lookup_allows_read_with_team_share(self) -> None:
        actor_id = uuid.uuid4()
        table = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            columns=[],
        )
        fake_db = _SequenceSession(
            [
                _SequenceQuery(first_result=None),
                _SequenceQuery(all_result=[]),
                _SequenceQuery(all_result=[(table, "read")]),
            ]
        )
        executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=actor_id)

        result = executor._get_accessible_data_table(fake_db, table.id, "getAll")

        self.assertIs(result, table)

    def test_upsert_insert_coerces_row_data_without_local_import_scope_error(self) -> None:
        table_id = uuid.uuid4()
        table = SimpleNamespace(
            id=table_id,
            owner_id=uuid.uuid4(),
            columns=[
                {"name": "username", "type": "string"},
                {"name": "githubToken", "type": "string"},
                {"name": "targetRepo", "type": "string"},
            ],
        )
        fake_db = _FakeDataTableSession(table)
        nodes = [
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "dataTable",
                    "dataTableId": str(table_id),
                    "dataTableOperation": "upsert",
                    "dataTableFilter": '{"username": "ada"}',
                    "dataTableData": (
                        '{"username": "ada", "githubToken": "tok", "targetRepo": ""}'
                    ),
                },
            }
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[], actor_user_id=table.owner_id)

        with patch("app.db.session.SessionLocal", return_value=fake_db):
            result = executor.execute_node("dt", {})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["operation"], "insert")
        self.assertEqual(fake_db.commits, 1)
        self.assertEqual(len(fake_db.added_rows), 1)
        self.assertEqual(
            fake_db.added_rows[0].data,
            {"username": "ada", "githubToken": "tok", "targetRepo": ""},
        )

    def test_data_table_lookup_allows_count_with_read_only_team_share(self) -> None:
        actor_id = uuid.uuid4()
        table = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), columns=[])
        fake_db = _SequenceSession(
            [
                _SequenceQuery(first_result=None),
                _SequenceQuery(all_result=[]),
                _SequenceQuery(all_result=[(table, "read")]),
            ]
        )
        executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=actor_id)

        result = executor._get_accessible_data_table(fake_db, table.id, "count")

        self.assertIs(result, table)

    def test_count_returns_total_without_filter(self) -> None:
        table_id = uuid.uuid4()
        table = SimpleNamespace(
            id=table_id,
            owner_id=uuid.uuid4(),
            columns=[{"name": "status", "type": "string"}],
        )
        fake_db = _FakeDataTableSession(table, count_result=7)
        nodes = [
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "dataTable",
                    "dataTableId": str(table_id),
                    "dataTableOperation": "count",
                },
            }
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[], actor_user_id=table.owner_id)

        with patch("app.db.session.SessionLocal", return_value=fake_db):
            result = executor.execute_node("dt", {})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["operation"], "count")
        self.assertEqual(result.output["count"], 7)
        self.assertTrue(result.output["success"])

    def test_count_returns_filtered_total(self) -> None:
        table_id = uuid.uuid4()
        table = SimpleNamespace(
            id=table_id,
            owner_id=uuid.uuid4(),
            columns=[
                {"name": "status", "type": "string"},
                {"name": "age", "type": "number"},
            ],
        )
        fake_db = _FakeDataTableSession(table, count_result=3)
        nodes = [
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "dataTable",
                    "dataTableId": str(table_id),
                    "dataTableOperation": "count",
                    "dataTableFilter": '{"status": "active", "age": {"$gt": 18}}',
                },
            }
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[], actor_user_id=table.owner_id)

        with patch("app.db.session.SessionLocal", return_value=fake_db):
            result = executor.execute_node("dt", {})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["operation"], "count")
        self.assertEqual(result.output["count"], 3)

    def test_find_uses_operator_filter_for_data_and_metadata_columns(self) -> None:
        from sqlalchemy.dialects import postgresql

        table_id = uuid.uuid4()
        table = SimpleNamespace(
            id=table_id,
            owner_id=uuid.uuid4(),
            columns=[
                {"name": "status", "type": "string"},
                {"name": "age", "type": "number"},
            ],
        )
        row = SimpleNamespace(
            id=uuid.uuid4(),
            data={"status": "active", "age": "21"},
            created_at="2026-06-04T12:00:00Z",
        )
        fake_db = _FakeDataTableSession(table, existing_row=[row])
        nodes = [
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "dataTable",
                    "dataTableId": str(table_id),
                    "dataTableOperation": "find",
                    "dataTableFilter": (
                        '{"status": "active", "age": {"$gte": 18}, '
                        '"created_at": {"$contains": "2026-06-04"}}'
                    ),
                },
            }
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=[], actor_user_id=table.owner_id)

        with patch("app.db.session.SessionLocal", return_value=fake_db):
            result = executor.execute_node("dt", {})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["operation"], "find")
        self.assertEqual(result.output["count"], 1)
        self.assertEqual(result.output["rows"][0]["data"], {"status": "active", "age": 21})
        self.assertIsNotNone(fake_db.last_row_query)
        filter_args = fake_db.last_row_query.filter_args
        self.assertEqual(len(filter_args), 2)
        operator_sql = " ".join(
            str(
                clause.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            for clause in filter_args[1]
        )
        self.assertIn("data ->> 'status'", operator_sql)
        self.assertIn("CAST", operator_sql.upper())
        self.assertIn("data_table_rows.created_at", operator_sql)
        self.assertIn("ILIKE", operator_sql.upper())


class DataTableFilterClauseTests(unittest.TestCase):
    """Unit tests for the Mongo-style operator -> SQLAlchemy clause builder."""

    @staticmethod
    def _sql(clause: object) -> str:
        from sqlalchemy.dialects import postgresql

        return str(
            clause.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

    def test_plain_value_is_equality(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"status": "active"}, [{"name": "status", "type": "string"}]
        )
        self.assertEqual(len(clauses), 1)
        sql = self._sql(clauses[0])
        self.assertIn("data ->> 'status'", sql)
        self.assertIn("= 'active'", sql)

    def test_ne_operator(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"status": {"$ne": "done"}}, [{"name": "status", "type": "string"}]
        )
        sql = self._sql(clauses[0])
        self.assertIn("data ->> 'status'", sql)
        self.assertIn("!= 'done'", sql)

    def test_gt_on_number_column_casts_to_numeric(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"age": {"$gt": 18}}, [{"name": "age", "type": "number"}]
        )
        sql = self._sql(clauses[0]).upper()
        self.assertIn("CAST", sql)
        self.assertIn("NUMERIC", sql)
        self.assertIn("> 18", sql)

    def test_gt_on_string_column_does_not_cast(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"name": {"$gt": "m"}}, [{"name": "name", "type": "string"}]
        )
        sql = self._sql(clauses[0])
        self.assertNotIn("CAST", sql.upper())
        self.assertIn("data ->> 'name'", sql)
        self.assertIn("> 'm'", sql)

    def test_contains_uses_ilike(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"name": {"$contains": "john"}}, [{"name": "name", "type": "string"}]
        )
        sql = self._sql(clauses[0]).upper()
        self.assertIn("ILIKE", sql)
        self.assertIn("%JOHN%", sql)

    def test_in_uses_in_clause(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"plan": {"$in": ["pro", "team"]}}, [{"name": "plan", "type": "string"}]
        )
        sql = self._sql(clauses[0]).upper()
        self.assertIn("IN (", sql)
        self.assertIn("'PRO'", sql)
        self.assertIn("'TEAM'", sql)

    def test_meta_created_at_maps_to_real_column(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"created_at": {"$gt": "2026-06-04"}}, [{"name": "status", "type": "string"}]
        )
        sql = self._sql(clauses[0])
        self.assertIn("data_table_rows.created_at", sql)
        self.assertNotIn("->>", sql)
        self.assertIn("> '2026-06-04'", sql)

    def test_meta_created_at_contains_casts_to_text(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses({"created_at": {"$contains": "06-04"}}, [])
        sql = self._sql(clauses[0]).upper()
        self.assertIn("CAST", sql)
        self.assertIn("ILIKE", sql)
        self.assertIn("%06-04%", sql)

    def test_meta_id_plain_value_maps_to_real_column(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses({"id": "abc-123"}, [])
        sql = self._sql(clauses[0])
        self.assertIn("data_table_rows.id", sql)
        self.assertNotIn("->>", sql)

    def test_schema_column_shadowing_meta_name_uses_json(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        # A user-defined data column literally named created_at must still use JSONB.
        clauses = _build_data_table_filter_clauses(
            {"created_at": "x"}, [{"name": "created_at", "type": "string"}]
        )
        sql = self._sql(clauses[0])
        self.assertIn("->>", sql)

    def test_unknown_operator_is_ignored(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        clauses = _build_data_table_filter_clauses(
            {"age": {"$regex": ".*"}}, [{"name": "age", "type": "number"}]
        )
        self.assertEqual(clauses, [])

    def test_empty_filter_yields_no_clauses(self) -> None:
        from app.services.workflow_executor import _build_data_table_filter_clauses

        self.assertEqual(_build_data_table_filter_clauses({}, []), [])


class CredentialContextTeamShareTests(unittest.IsolatedAsyncioTestCase):
    async def test_workflow_credentials_context_includes_team_shared_credentials(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Team Bearer",
            type=CredentialType.bearer,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([]),
                _ScalarsResult([]),
                _ScalarsResult([credential]),
            ]
        )

        with patch("app.api.workflows.decrypt_config", return_value={"bearer_token": "tok"}):
            context = await get_credentials_context(db, user_id)

        self.assertEqual(context, {"Team Bearer": "Bearer tok"})

    async def test_mcp_credentials_context_includes_team_shared_credentials(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Team Header",
            type=CredentialType.header,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([]),
                _ScalarsResult([]),
                _ScalarsResult([credential]),
            ]
        )

        with patch(
            "app.api.mcp.decrypt_config",
            return_value={"header_key": "X-API-Key", "header_value": "secret"},
        ):
            context = await get_credentials_context_for_user(db, user_id)

        self.assertEqual(context, {"Team Header": "X-API-Key: secret"})

    async def test_workflow_credentials_context_includes_discord_webhook_url(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Discord Alerts",
            type=CredentialType.discord,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        webhook_url = "https://discord.com/api/webhooks/123/abc"
        with patch("app.api.workflows.decrypt_config", return_value={"webhook_url": webhook_url}):
            context = await get_credentials_context(db, user_id)

        self.assertEqual(context, {"Discord Alerts": webhook_url})

    async def test_mcp_credentials_context_includes_discord_webhook_url(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Discord Alerts",
            type=CredentialType.discord,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        webhook_url = "https://discord.com/api/webhooks/123/abc"
        with patch("app.api.mcp.decrypt_config", return_value={"webhook_url": webhook_url}):
            context = await get_credentials_context_for_user(db, user_id)

        self.assertEqual(context, {"Discord Alerts": webhook_url})

    async def test_workflow_credentials_context_includes_github_token(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="GitHub Token",
            type=CredentialType.github,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        with patch(
            "app.api.workflows.decrypt_config",
            return_value={"api_key": "github_pat_123"},
        ):
            context = await get_credentials_context(db, user_id)

        self.assertEqual(context, {"GitHub Token": "github_pat_123"})

    async def test_workflow_credentials_context_includes_notion_token(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Notion Token",
            type=CredentialType.notion,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        with patch(
            "app.api.workflows.decrypt_config",
            return_value={"api_token": "ntn_secret"},
        ):
            context = await get_credentials_context(db, user_id)

        self.assertEqual(context, {"Notion Token": "ntn_secret"})

    async def test_workflow_credentials_context_includes_notion_oauth_token(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Notion OAuth",
            type=CredentialType.notion,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        with patch(
            "app.api.workflows.decrypt_config",
            return_value={"auth_mode": "oauth", "access_token": "oauth-secret"},
        ):
            context = await get_credentials_context(db, user_id)

        self.assertEqual(context, {"Notion OAuth": "oauth-secret"})

    async def test_mcp_credentials_context_includes_notion_token(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Notion Token",
            type=CredentialType.notion,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        with patch(
            "app.api.mcp.decrypt_config",
            return_value={"api_token": "ntn_secret"},
        ):
            context = await get_credentials_context_for_user(db, user_id)

        self.assertEqual(context, {"Notion Token": "ntn_secret"})

    async def test_mcp_credentials_context_includes_notion_oauth_token(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Notion OAuth",
            type=CredentialType.notion,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        with patch(
            "app.api.mcp.decrypt_config",
            return_value={"auth_mode": "oauth", "access_token": "oauth-secret"},
        ):
            context = await get_credentials_context_for_user(db, user_id)

        self.assertEqual(context, {"Notion OAuth": "oauth-secret"})

    async def test_mcp_credentials_context_includes_github_token(self) -> None:
        user_id = uuid.uuid4()
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="GitHub Token",
            type=CredentialType.github,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _ScalarsResult([credential]),
                _ScalarsResult([]),
                _ScalarsResult([]),
            ]
        )

        with patch(
            "app.api.mcp.decrypt_config",
            return_value={"api_key": "github_pat_123"},
        ):
            context = await get_credentials_context_for_user(db, user_id)

        self.assertEqual(context, {"GitHub Token": "github_pat_123"})


class ParseExecuteBodyXTriggerSourceTests(unittest.IsolatedAsyncioTestCase):
    """X-Trigger-Source header support in parse_execute_body."""

    async def test_reads_trigger_source_from_header_when_no_query_param(self) -> None:
        request = make_request(
            body=b"{}",
            headers=[(b"x-trigger-source", b"API")],
        )
        _, _, trigger_source, _ = await parse_execute_body(request)
        self.assertEqual(trigger_source, "API")

    async def test_custom_caller_label_preserved_from_header(self) -> None:
        request = make_request(
            body=b"{}",
            headers=[(b"x-trigger-source", b"rabbitmq")],
        )
        _, _, trigger_source, _ = await parse_execute_body(request)
        self.assertEqual(trigger_source, "rabbitmq")

    async def test_query_param_takes_priority_over_header(self) -> None:
        request = make_request(
            body=b"{}",
            query_string=b"trigger_source=Canvas",
            headers=[(b"x-trigger-source", b"API")],
        )
        _, _, trigger_source, _ = await parse_execute_body(request)
        self.assertEqual(trigger_source, "Canvas")

    async def test_whitespace_only_header_treated_as_missing(self) -> None:
        request = make_request(
            body=b"{}",
            headers=[(b"x-trigger-source", b"   ")],
        )
        _, _, trigger_source, _ = await parse_execute_body(request)
        self.assertEqual(trigger_source, "API")

    async def test_missing_header_and_missing_query_param_defaults_to_api(self) -> None:
        request = make_request(body=b"{}")
        _, _, trigger_source, _ = await parse_execute_body(request)
        self.assertEqual(trigger_source, "API")


class SubWorkflowTriggerSourceTests(unittest.IsolatedAsyncioTestCase):
    """Sub-workflow history entries must always be stored with trigger_source='SUB_WORKFLOW'."""

    def _make_workflow(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            name="Parent Workflow",
        )

    def _make_execution_result(
        self, workflow_id: uuid.UUID, *, sub_workflow_id: str
    ) -> ExecutionResult:
        sub_exec = SubWorkflowExecution(
            workflow_id=sub_workflow_id,
            inputs={"text": "hello"},
            outputs={"result": "ok"},
            status="success",
            execution_time_ms=42.0,
            workflow_name="Child Workflow",
        )
        return ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"result": "ok"},
            execution_time_ms=100.0,
            sub_workflow_executions=[sub_exec],
        )

    async def test_sub_workflow_history_saved_with_sub_workflow_trigger_source(self) -> None:
        workflow = self._make_workflow()
        sub_workflow_id = str(uuid.uuid4())
        execution_result = self._make_execution_result(workflow.id, sub_workflow_id=sub_workflow_id)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        recorded_history_calls: list[dict] = []

        def capture_history(**kwargs: object) -> SimpleNamespace:
            recorded_history_calls.append(dict(kwargs))
            return SimpleNamespace(id=uuid.uuid4())

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.workflows.ExecutionHistory", side_effect=capture_history),
        ):
            await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(query_string=b"trigger_source=API"),
                current_user=None,
                db=db,
            )

        # First call is the parent history entry, second is the sub-workflow entry.
        self.assertEqual(len(recorded_history_calls), 2)
        parent_call = recorded_history_calls[0]
        sub_call = recorded_history_calls[1]

        self.assertEqual(parent_call["trigger_source"], "API")
        self.assertEqual(sub_call["trigger_source"], "SUB_WORKFLOW")
        self.assertEqual(str(sub_call["workflow_id"]), sub_workflow_id)

    async def test_parent_trigger_source_not_leaked_to_sub_workflow(self) -> None:
        """Regardless of the parent trigger_source, sub entries always get SUB_WORKFLOW."""
        workflow = self._make_workflow()
        sub_workflow_id = str(uuid.uuid4())
        execution_result = self._make_execution_result(workflow.id, sub_workflow_id=sub_workflow_id)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        recorded_trigger_sources: list[str | None] = []

        def capture_trigger_source(**kwargs: object) -> SimpleNamespace:
            recorded_trigger_sources.append(kwargs.get("trigger_source"))  # type: ignore[arg-type]
            return SimpleNamespace(id=uuid.uuid4())

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.workflows.ExecutionHistory", side_effect=capture_trigger_source),
        ):
            # Trigger the workflow as if from an internal Canvas run.
            await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(query_string=b"trigger_source=Canvas"),
                current_user=None,
                db=db,
            )

        # Parent gets "Canvas"; sub-workflow must NOT inherit it.
        self.assertEqual(recorded_trigger_sources[0], "Canvas")
        self.assertEqual(recorded_trigger_sources[1], "SUB_WORKFLOW")


class TestRunExecuteNoHistoryTests(unittest.IsolatedAsyncioTestCase):
    """test_run=True (e.g. expression preview) must not insert ExecutionHistory rows."""

    def _make_workflow(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "textInput", "data": {"label": "Input"}}],
            edges=[],
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_enabled=False,
            name="Preview",
        )

    async def test_test_run_success_does_not_create_execution_history(self) -> None:
        workflow = self._make_workflow()
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"out": 1},
            execution_time_ms=5.0,
            node_results=[],
            sub_workflow_executions=[],
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        db.flush = AsyncMock()

        execution_history_ctor = MagicMock()

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.workflows.ExecutionHistory", execution_history_ctor),
        ):
            await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(query_string=b"test_run=true&trigger_source=Canvas"),
                current_user=None,
                db=db,
            )

        execution_history_ctor.assert_not_called()

    async def test_test_run_with_sub_workflow_does_not_create_history_rows(self) -> None:
        workflow = self._make_workflow()
        sub_wf_id = str(uuid.uuid4())
        sub_exec = SubWorkflowExecution(
            workflow_id=sub_wf_id,
            inputs={},
            outputs={},
            status="success",
            execution_time_ms=1.0,
            workflow_name="Child",
        )
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={"out": 1},
            execution_time_ms=5.0,
            node_results=[],
            sub_workflow_executions=[sub_exec],
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        db.flush = AsyncMock()

        execution_history_ctor = MagicMock()

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows._persist_global_variables_from_execution", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch("app.api.workflows.ExecutionHistory", execution_history_ctor),
        ):
            await execute_workflow_endpoint(
                workflow_id=workflow.id,
                request=make_request(query_string=b"test_run=true&trigger_source=Canvas"),
                current_user=None,
                db=db,
            )

        execution_history_ctor.assert_not_called()

    async def test_test_run_cancelled_does_not_create_execution_history(self) -> None:
        workflow = self._make_workflow()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        db.commit = AsyncMock()

        execution_history_ctor = MagicMock()

        with (
            patch("app.api.workflows.validate_workflow_auth", AsyncMock()),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch(
                "app.api.workflows.asyncio.to_thread",
                AsyncMock(side_effect=WorkflowCancelledError("cancelled")),
            ),
            patch("app.api.workflows.ExecutionHistory", execution_history_ctor),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await execute_workflow_endpoint(
                    workflow_id=workflow.id,
                    request=make_request(query_string=b"test_run=true&trigger_source=Canvas"),
                    current_user=None,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        execution_history_ctor.assert_not_called()
        db.add.assert_not_called()
        db.commit.assert_not_called()


class AutoRecoverRunsSchemaTests(unittest.TestCase):
    def test_workflow_response_defaults_auto_recover_true(self) -> None:
        from app.models.schemas import WorkflowResponse

        fields = WorkflowResponse.model_fields
        self.assertIn("auto_recover_runs", fields)
        self.assertEqual(fields["auto_recover_runs"].default, True)

    def test_workflow_update_accepts_auto_recover(self) -> None:
        from app.models.schemas import WorkflowUpdate

        self.assertIn("auto_recover_runs", WorkflowUpdate.model_fields)
        update = WorkflowUpdate(auto_recover_runs=False)
        self.assertFalse(update.auto_recover_runs)
