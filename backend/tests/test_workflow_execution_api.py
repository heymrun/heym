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
from app.api.portal import portal_cancel_execution
from app.api.workflows import execute_workflow_endpoint, execute_workflow_stream, parse_execute_body
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

        with patch("app.api.portal.cancel_active_execution", return_value=True) as cancel_mock:
            result = await portal_cancel_execution(
                slug="portal-test",
                execution_id=execution_id,
                request=make_request(),
                db=db,
            )

        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_mock.assert_called_once_with(workflow_id=workflow_id, execution_id=execution_id)

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

        with patch("app.api.portal.cancel_active_execution", return_value=False):
            with self.assertRaises(HTTPException) as context:
                await portal_cancel_execution(
                    slug="portal-test",
                    execution_id=execution_id,
                    request=make_request(),
                    db=db,
                )

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.detail, "Execution not found or already finished")


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
