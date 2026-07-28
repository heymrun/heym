"""Tests for OpenTelemetry tracing instrumentation.

These exercise the span seams in the workflow executor and the read-only status
endpoint without depending on real node logic. Inner methods are patched so the
tests assert only the instrumentation behavior.
"""

import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability import tracing
from app.services.workflow_executor import (
    ExecutionResult,
    NodeResult,
    WorkflowExecutor,
)


def _make_executor() -> WorkflowExecutor:
    nodes = [{"id": "n1", "type": "set", "data": {"label": "My Node"}}]
    return WorkflowExecutor(nodes=nodes, edges=[], workflow_id=uuid.uuid4())


def _success_result() -> NodeResult:
    return NodeResult(
        node_id="n1",
        node_label="My Node",
        node_type="set",
        status="success",
        output={"value": 1},
        execution_time_ms=2.0,
    )


class TracingDisabledTest(unittest.TestCase):
    def test_get_tracer_is_safe_when_disabled(self) -> None:
        self.assertFalse(tracing.is_enabled())
        tracer = tracing.get_tracer()
        with tracer.start_as_current_span("x") as span:
            span.set_attribute("heym.test", 1)
        self.assertIsNotNone(tracer)

    def test_agent_tool_span_is_noop_when_disabled(self) -> None:
        self.assertFalse(tracing.is_enabled())
        with tracing.agent_tool_span(
            tool_name="fetch_data",
            tool_call_id="call-1",
            source="node_tool",
        ) as span:
            self.assertIsNone(span)
            tracing.set_span_attribute(span, "heym.agent.tool.status", "success")
            tracing.record_agent_tool_exception(span, RuntimeError("ignored"))

    def test_execute_node_takes_noop_fast_path_when_disabled(self) -> None:
        executor = _make_executor()
        with patch.object(executor, "_execute_node_inner", return_value=_success_result()) as inner:
            result = executor.execute_node("n1", {})
        self.assertEqual(result.status, "success")
        inner.assert_called_once()


class _EnabledTracingTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        # Bypass set-once guard so each test gets a fresh global provider.
        self._saved_global = trace._TRACER_PROVIDER
        trace._TRACER_PROVIDER = provider
        tracing._provider = provider  # mark tracing "enabled"

    def tearDown(self) -> None:
        tracing._provider = None
        trace._TRACER_PROVIDER = self._saved_global


class NodeSpanTest(_EnabledTracingTestBase):
    def test_node_span_emitted_with_attributes(self) -> None:
        executor = _make_executor()
        with patch.object(executor, "_execute_node_inner", return_value=_success_result()):
            executor.execute_node("n1", {})
        spans = self.exporter.get_finished_spans()
        node_spans = [s for s in spans if s.name == "heym.node.execute"]
        self.assertEqual(len(node_spans), 1)
        attrs = dict(node_spans[0].attributes)
        self.assertEqual(attrs["heym.node.id"], "n1")
        self.assertEqual(attrs["heym.node.type"], "set")
        self.assertEqual(attrs["heym.node.label"], "My Node")
        self.assertEqual(attrs["heym.node.status"], "success")

    def test_node_span_marks_error_status(self) -> None:
        executor = _make_executor()
        err = NodeResult(
            node_id="n1",
            node_label="My Node",
            node_type="set",
            status="error",
            output={"error": "boom"},
            execution_time_ms=1.0,
            error="boom",
        )
        with patch.object(executor, "_execute_node_inner", return_value=err):
            executor.execute_node("n1", {})
        node_spans = [
            s for s in self.exporter.get_finished_spans() if s.name == "heym.node.execute"
        ]
        self.assertEqual(len(node_spans), 1)
        self.assertEqual(node_spans[0].status.status_code, trace.StatusCode.ERROR)

    def test_llm_token_attributes_from_usage(self) -> None:
        executor = _make_executor()
        llm_result = NodeResult(
            node_id="n1",
            node_label="My Node",
            node_type="llm",
            status="success",
            output={
                "model": "gpt-4o",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
            execution_time_ms=3.0,
        )
        with patch.object(executor, "_execute_node_inner", return_value=llm_result):
            executor.execute_node("n1", {})
        attrs = dict(
            [s for s in self.exporter.get_finished_spans() if s.name == "heym.node.execute"][
                0
            ].attributes
        )
        self.assertEqual(attrs["heym.llm.model"], "gpt-4o")
        self.assertEqual(attrs["heym.llm.total_tokens"], 15)
        self.assertEqual(attrs["heym.llm.prompt_tokens"], 10)

    def test_agent_tool_span_has_tool_identity_and_status(self) -> None:
        with tracing.agent_tool_span(
            tool_name="fetch_data",
            tool_call_id="call-1",
            source="node_tool",
            mcp_server="weather",
            workflow_id="workflow-1",
            node_id="agent-1",
            node_label="Research Agent",
            iteration=2,
        ) as span:
            span.set_attribute("heym.agent.tool.status", "success")

        tool_spans = [
            s for s in self.exporter.get_finished_spans() if s.name == "heym.agent.tool.execute"
        ]
        self.assertEqual(len(tool_spans), 1)
        attrs = dict(tool_spans[0].attributes)
        self.assertEqual(attrs["heym.agent.tool.name"], "fetch_data")
        self.assertEqual(attrs["heym.agent.tool.call_id"], "call-1")
        self.assertEqual(attrs["heym.agent.tool.source"], "node_tool")
        self.assertEqual(attrs["heym.agent.tool.mcp_server"], "weather")
        self.assertEqual(attrs["heym.workflow.id"], "workflow-1")
        self.assertEqual(attrs["heym.node.id"], "agent-1")
        self.assertEqual(attrs["heym.node.label"], "Research Agent")
        self.assertEqual(attrs["heym.agent.tool.iteration"], 2)
        self.assertEqual(attrs["heym.agent.tool.status"], "success")

    def test_agent_tool_span_nests_under_agent_node_span(self) -> None:
        """Tool spans from execute_with_tools must nest under the Agent node span.

        Production Agent execution opens the node span in ``execute_node``, then
        reaches ``LLMService.execute_with_tools`` via ``run_async`` / ``asyncio.run``
        and runs tool bodies with ``asyncio.to_thread``. This regression covers that
        path instead of calling ``agent_tool_span`` directly inside a patched inner.
        """
        from types import SimpleNamespace

        from app.db.models import CredentialType
        from app.services.llm_service import LLMService
        from app.services.workflow_executor import run_async

        executor = WorkflowExecutor(
            nodes=[{"id": "agent-1", "type": "agent", "data": {"label": "Research Agent"}}],
            edges=[],
            workflow_id=uuid.uuid4(),
        )
        node_result = NodeResult(
            node_id="agent-1",
            node_label="Research Agent",
            node_type="agent",
            status="success",
            output={"text": "done"},
            execution_time_ms=2.0,
        )

        def fake_agent_inner(*_args: object, **_kwargs: object) -> NodeResult:
            tool_call = SimpleNamespace(
                id="call-child",
                type="function",
                function=SimpleNamespace(name="fetch_data", arguments="{}"),
            )
            responses = [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=None, tool_calls=[tool_call])
                        )
                    ],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=[]))
                    ],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                ),
            ]

            def create(**_create_kwargs: object) -> SimpleNamespace:
                return responses.pop(0)

            client = SimpleNamespace(
                base_url="http://test",
                chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            )
            service = LLMService(CredentialType.openai, "test-key")

            def tool_executor(*_tool_args: object) -> dict[str, object]:
                return {"ok": True, "status": "success"}

            with patch.object(service, "_get_client", return_value=(client, "Test")):
                run_async(
                    service.execute_with_tools(
                        model="test-model",
                        system_instruction=None,
                        user_message="run tool",
                        tools=[
                            {
                                "name": "fetch_data",
                                "parameters": {"type": "object"},
                                "_source": "node_tool",
                            }
                        ],
                        tool_executor=tool_executor,
                    )
                )
            return node_result

        with patch.object(executor, "_execute_node_inner", side_effect=fake_agent_inner):
            executor.execute_node("agent-1", {})

        spans = self.exporter.get_finished_spans()
        node_span = next(span for span in spans if span.name == "heym.node.execute")
        tool_span = next(span for span in spans if span.name == "heym.agent.tool.execute")
        self.assertIsNotNone(tool_span.parent)
        self.assertEqual(tool_span.parent.span_id, node_span.context.span_id)
        self.assertEqual(tool_span.context.trace_id, node_span.context.trace_id)
        self.assertEqual(dict(tool_span.attributes)["heym.agent.tool.name"], "fetch_data")
        self.assertEqual(dict(tool_span.attributes)["heym.agent.tool.call_id"], "call-child")

    def test_agent_tool_span_nests_when_run_async_uses_worker_thread(self) -> None:
        """When a loop is already running, run_async must reattach OTel context."""
        import asyncio
        from types import SimpleNamespace

        from app.db.models import CredentialType
        from app.services.llm_service import LLMService
        from app.services.workflow_executor import run_async

        executor = WorkflowExecutor(
            nodes=[{"id": "agent-1", "type": "agent", "data": {"label": "Research Agent"}}],
            edges=[],
            workflow_id=uuid.uuid4(),
        )
        node_result = NodeResult(
            node_id="agent-1",
            node_label="Research Agent",
            node_type="agent",
            status="success",
            output={"text": "done"},
            execution_time_ms=2.0,
        )

        def fake_agent_inner(*_args: object, **_kwargs: object) -> NodeResult:
            tool_call = SimpleNamespace(
                id="call-thread",
                type="function",
                function=SimpleNamespace(name="fetch_data", arguments="{}"),
            )
            responses = [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=None, tool_calls=[tool_call])
                        )
                    ],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=[]))
                    ],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                ),
            ]

            def create(**_create_kwargs: object) -> SimpleNamespace:
                return responses.pop(0)

            client = SimpleNamespace(
                base_url="http://test",
                chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            )
            service = LLMService(CredentialType.openai, "test-key")

            with patch.object(service, "_get_client", return_value=(client, "Test")):
                run_async(
                    service.execute_with_tools(
                        model="test-model",
                        system_instruction=None,
                        user_message="run tool",
                        tools=[
                            {
                                "name": "fetch_data",
                                "parameters": {"type": "object"},
                                "_source": "node_tool",
                            }
                        ],
                        tool_executor=lambda *_tool_args: {"ok": True},
                    )
                )
            return node_result

        async def _drive() -> None:
            with patch.object(executor, "_execute_node_inner", side_effect=fake_agent_inner):
                executor.execute_node("agent-1", {})

        asyncio.run(_drive())

        spans = self.exporter.get_finished_spans()
        node_span = next(span for span in spans if span.name == "heym.node.execute")
        tool_span = next(span for span in spans if span.name == "heym.agent.tool.execute")
        self.assertIsNotNone(tool_span.parent)
        self.assertEqual(tool_span.parent.span_id, node_span.context.span_id)
        self.assertEqual(tool_span.context.trace_id, node_span.context.trace_id)

    def test_agent_tool_span_records_uncaught_exception(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "tool exploded"):
            with tracing.agent_tool_span(
                tool_name="fetch_data",
                tool_call_id="call-2",
                source="node_tool",
            ):
                raise RuntimeError("tool exploded")

        tool_span = next(
            s for s in self.exporter.get_finished_spans() if s.name == "heym.agent.tool.execute"
        )
        self.assertEqual(tool_span.status.status_code, trace.StatusCode.ERROR)
        self.assertTrue(any(event.name == "exception" for event in tool_span.events))

    def test_agent_tool_exception_redacts_sensitive_error_text(self) -> None:
        with tracing.agent_tool_span(
            tool_name="fetch_data",
            tool_call_id="call-secret",
            source="node_tool",
        ) as span:
            tracing.record_agent_tool_exception(
                span,
                RuntimeError("upstream failed: api_key=sk-super-secret"),
            )

        tool_span = next(
            s for s in self.exporter.get_finished_spans() if s.name == "heym.agent.tool.execute"
        )
        serialized = repr(
            {
                "status": tool_span.status.description,
                "events": [
                    {"name": event.name, "attributes": dict(event.attributes)}
                    for event in tool_span.events
                ],
            }
        )
        self.assertNotIn("sk-super-secret", serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_set_span_status_failure_is_swallowed(self) -> None:
        class BrokenSpan:
            def set_status(self, *_args: object, **_kwargs: object) -> None:
                raise RuntimeError("otel broken")

        tracing.set_span_status(BrokenSpan(), trace.StatusCode.ERROR, "boom")


class WorkflowSpanTest(_EnabledTracingTestBase):
    def test_root_span_emitted(self) -> None:
        executor = _make_executor()
        wf_id = executor.workflow_id
        result = ExecutionResult(
            workflow_id=wf_id, status="success", outputs={}, execution_time_ms=5.0
        )
        with patch.object(executor, "_execute_inner", return_value=result):
            executor.execute(wf_id, {})
        root_spans = [
            s for s in self.exporter.get_finished_spans() if s.name == "heym.workflow.execute"
        ]
        self.assertEqual(len(root_spans), 1)
        attrs = dict(root_spans[0].attributes)
        self.assertEqual(attrs["heym.workflow.id"], str(wf_id))
        self.assertEqual(attrs["heym.node.count"], 1)

    def test_node_span_nests_under_workflow_span_across_threads(self) -> None:
        """Node spans created in worker threads must parent to the workflow span."""
        executor = _make_executor()
        wf_id = executor.workflow_id

        def fake_inner(_wf_id: uuid.UUID, _inputs: dict) -> ExecutionResult:
            # Run node execution in a worker thread, like the real parallel path.
            with patch.object(executor, "_execute_node_inner", return_value=_success_result()):
                pool = ThreadPoolExecutor(max_workers=1)
                fut = pool.submit(executor.execute_node, "n1", {})
                fut.result()
                pool.shutdown()
            return ExecutionResult(
                workflow_id=_wf_id, status="success", outputs={}, execution_time_ms=5.0
            )

        with patch.object(executor, "_execute_inner", side_effect=fake_inner):
            executor.execute(wf_id, {})

        spans = self.exporter.get_finished_spans()
        root = next(s for s in spans if s.name == "heym.workflow.execute")
        node = next(s for s in spans if s.name == "heym.node.execute")
        self.assertEqual(node.parent.span_id, root.context.span_id)
        self.assertEqual(node.context.trace_id, root.context.trace_id)


class StreamingRootSpanTest(_EnabledTracingTestBase):
    def test_streaming_wrapper_opens_root_span_and_nests_nodes(self) -> None:
        """The canvas/portal streaming path must still emit heym.workflow.execute."""
        from app.services import workflow_executor as wfe

        captured: dict = {}

        def fake_impl(*, otel_root_context=None, **_kwargs):
            captured["ctx"] = otel_root_context

            def _make_node_span() -> list:
                tracer = tracing.get_tracer()
                with tracer.start_as_current_span("heym.node.execute") as s:
                    s.set_attribute("heym.node.type", "set")
                return [{"type": "node_complete"}]

            if otel_root_context is not None:
                events = tracing.run_with_context(otel_root_context, _make_node_span)
            else:
                events = _make_node_span()
            yield from events

        with patch.object(wfe, "_execute_workflow_streaming_impl", fake_impl):
            events = list(
                wfe.execute_workflow_streaming(
                    workflow_id=uuid.uuid4(), nodes=[{"id": "n1"}], edges=[], inputs={}
                )
            )

        self.assertEqual(len(events), 1)
        self.assertIsNotNone(captured["ctx"])
        spans = self.exporter.get_finished_spans()
        root = next(s for s in spans if s.name == "heym.workflow.execute")
        node = next(s for s in spans if s.name == "heym.node.execute")
        self.assertEqual(node.parent.span_id, root.context.span_id)
        self.assertEqual(node.context.trace_id, root.context.trace_id)


class CaptureNodeIoTest(_EnabledTracingTestBase):
    def test_node_io_attached_only_when_enabled(self) -> None:
        from app.api import config as config_api

        executor = _make_executor()
        io_result = NodeResult(
            node_id="n1",
            node_label="My Node",
            node_type="set",
            status="success",
            output={"value": 42},
            execution_time_ms=1.0,
        )
        with (
            patch.object(config_api.settings, "otel_capture_node_io", True),
            patch.object(executor, "_execute_node_inner", return_value=io_result),
        ):
            executor.execute_node("n1", {"in": "hello"})
        attrs = dict(
            [s for s in self.exporter.get_finished_spans() if s.name == "heym.node.execute"][
                0
            ].attributes
        )
        self.assertIn("heym.node.input", attrs)
        self.assertIn("heym.node.output", attrs)
        self.assertIn("hello", attrs["heym.node.input"])
        self.assertIn("42", attrs["heym.node.output"])


class ObservabilityStatusEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_status_disabled_shape(self) -> None:
        from app.api import config as config_api

        # Patch off explicitly so the test does not depend on the ambient .env.
        with patch.object(config_api.settings, "otel_enabled", False):
            status = await config_api.get_observability_status(_user=object())
        dumped = status.model_dump()
        self.assertFalse(dumped["enabled"])
        self.assertEqual(dumped["instrumented"], [])
        self.assertEqual(dumped["spans"], [])
        self.assertNotIn("headers", dumped)
        self.assertEqual(dumped["endpoint"], "")

    async def test_status_enabled_no_secret_leak(self) -> None:
        from app.api import config as config_api

        with (
            patch.object(config_api.settings, "otel_enabled", True),
            patch.object(
                config_api.settings, "otel_exporter_otlp_endpoint", "http://collector:4318"
            ),
            patch.object(
                config_api.settings, "otel_exporter_otlp_headers", "authorization=Bearer secret"
            ),
        ):
            status = await config_api.get_observability_status(_user=object())
        dumped = status.model_dump()
        self.assertTrue(dumped["enabled"])
        self.assertEqual(dumped["endpoint"], "http://collector:4318")
        self.assertEqual(dumped["instrumented"], ["fastapi", "httpx"])
        self.assertEqual(dumped["spans"], ["workflow", "node", "agent_tool"])
        # No secret/header value anywhere in the serialized status.
        self.assertNotIn("secret", str(dumped).lower())
        self.assertNotIn("authorization", str(dumped).lower())


if __name__ == "__main__":
    unittest.main()
