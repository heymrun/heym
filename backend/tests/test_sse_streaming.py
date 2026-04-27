"""Unit tests for SSE streaming workflow configuration."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.workflows import update_workflow
from app.models.schemas import NodeResultSchema, WorkflowUpdate
from app.services.workflow_executor import (
    NodeResult,
    WorkflowExecutor,
    build_node_start_message,
    execute_workflow_streaming,
)

_FAKE_NODE_OUTPUT = {
    "text": "Hello world",
    "structured": {"count": 2, "items": ["a", "b"]},
}


class BuildNodeStartMessageTests(unittest.TestCase):
    """Verify build_node_start_message returns correct message or None."""

    def test_default_message_when_no_config(self) -> None:
        result = build_node_start_message("node-1", "LLM", None)
        self.assertEqual(result, "[START] LLM")

    def test_default_message_when_empty_config(self) -> None:
        result = build_node_start_message("node-1", "LLM", {})
        self.assertEqual(result, "[START] LLM")

    def test_default_message_when_node_not_in_config(self) -> None:
        config = {"other-node": {"send_start": True, "start_message": "Hi"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "[START] LLM")

    def test_custom_message_from_config(self) -> None:
        config = {"node-1": {"send_start": True, "start_message": "Custom start"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "Custom start")

    def test_null_start_message_falls_back_to_default(self) -> None:
        config = {"node-1": {"send_start": True, "start_message": None}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "[START] LLM")

    def test_empty_start_message_falls_back_to_default(self) -> None:
        config = {"node-1": {"send_start": True, "start_message": ""}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "[START] LLM")

    def test_returns_none_when_send_start_false(self) -> None:
        config = {"node-1": {"send_start": False, "start_message": None}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertIsNone(result)

    def test_returns_none_when_send_start_false_even_with_message(self) -> None:
        config = {"node-1": {"send_start": False, "start_message": "Should not appear"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertIsNone(result)

    def test_default_send_start_is_true(self) -> None:
        config = {"node-1": {"start_message": "Hello"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "Hello")


class _FakeWorkflowExecutor:
    def __init__(
        self,
        nodes: list[dict],
        edges: list[dict],
        workflow_cache: dict[str, dict] | None = None,
        test_mode: bool = False,
        credentials_context: dict[str, str] | None = None,
        global_variables_context: dict[str, object] | None = None,
        workflow_id: uuid.UUID | None = None,
        trace_user_id: uuid.UUID | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        agent_progress_queue: object | None = None,
        cancel_event: object | None = None,
        public_base_url: str = "",  # noqa: ARG002
    ) -> None:
        self.nodes = {node["id"]: node for node in nodes}
        self.edges = list(edges)
        self._active_edges = list(edges)
        self.delegated_agent_node_results: list[NodeResult] = []
        self.retry_node_results: list[NodeResult] = []
        self.sub_workflow_executions: list[object] = []
        self.inactive_nodes: set[str] = set()
        self.skipped_nodes: set[str] = set()
        self.loop_states: dict[str, dict[str, int]] = {}
        self.node_outputs: dict[str, dict] = {}
        self._cancel_event = cancel_event
        self._sequence = 0

    def get_error_flow_nodes(self) -> set[str]:
        return set()

    def get_active_edges(self) -> list[dict]:
        return list(self._active_edges)

    def get_input_nodes(self) -> list[str]:
        return list(self.nodes.keys())

    def check_cancelled(self) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise RuntimeError("cancelled")

    def get_node_inputs_for_edges(self, node_id: str, active_edges: list[dict]) -> dict:
        del node_id, active_edges
        return {}

    def execute_node_parallel(
        self,
        node_id: str,
        node_inputs: dict,
        on_retry: object | None = None,
    ) -> NodeResult:
        del node_inputs, on_retry
        node = self.nodes[node_id]
        node_label = node.get("data", {}).get("label", node_id)
        self.node_outputs[node_id] = _FAKE_NODE_OUTPUT
        return self._stamp_node_result(
            NodeResult(
                node_id=node_id,
                node_label=node_label,
                node_type=node.get("type", "unknown"),
                status="success",
                output=_FAKE_NODE_OUTPUT,
                execution_time_ms=12.5,
            )
        )

    def _stamp_node_result(self, result: NodeResult) -> NodeResult:
        self._sequence += 1
        ended_at_ms = 1000.0 + (self._sequence * 25)
        result.metadata = {
            **dict(result.metadata or {}),
            "sequence": self._sequence,
            "started_at_ms": ended_at_ms - result.execution_time_ms,
            "ended_at_ms": ended_at_ms,
        }
        return result

    def get_branch_node_ids(self, downstream_target: str, active_edges: list[dict]) -> set[str]:
        del downstream_target, active_edges
        return set()

    def get_incoming_edge_count_for_execution(
        self,
        branch_node: str,
        active_edges: list[dict],
    ) -> int:
        del branch_node, active_edges
        return 0

    def get_output_nodes(self) -> list[str]:
        return list(self.nodes.keys())

    def get_node_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id, {})
        return node.get("data", {}).get("label", node_id)


class ExecuteWorkflowStreamingSseTests(unittest.TestCase):
    def _collect_events(self, sse_node_config: dict | None = None) -> list[dict]:
        nodes = [{"id": "node-1", "type": "llm", "data": {"label": "LLM"}}]
        with patch("app.services.workflow_executor.WorkflowExecutor", _FakeWorkflowExecutor):
            return list(
                execute_workflow_streaming(
                    workflow_id=uuid.uuid4(),
                    nodes=nodes,
                    edges=[],
                    inputs={},
                    sse_node_config=sse_node_config,
                )
            )

    def test_node_start_message_from_config(self) -> None:
        events = self._collect_events(
            {"node-1": {"send_start": True, "start_message": "Custom start"}}
        )

        node_start = next(event for event in events if event.get("type") == "node_start")
        self.assertEqual(node_start.get("message"), "Custom start")

    def test_node_start_default_message_when_no_config(self) -> None:
        events = self._collect_events()

        node_start = next(event for event in events if event.get("type") == "node_start")
        self.assertEqual(node_start.get("message"), "[START] LLM")

    def test_node_start_no_message_when_send_start_false(self) -> None:
        events = self._collect_events({"node-1": {"send_start": False, "start_message": None}})

        node_start = next(event for event in events if event.get("type") == "node_start")
        self.assertNotIn("message", node_start)

    def test_node_complete_always_emitted_with_full_output(self) -> None:
        events = self._collect_events({"node-1": {"send_start": False, "start_message": None}})

        node_complete = next(event for event in events if event.get("type") == "node_complete")
        self.assertEqual(node_complete.get("output"), _FAKE_NODE_OUTPUT)
        self.assertEqual(node_complete.get("status"), "success")
        self.assertEqual(node_complete.get("metadata", {}).get("sequence"), 1)
        self.assertEqual(node_complete.get("metadata", {}).get("started_at_ms"), 1012.5)
        self.assertEqual(node_complete.get("metadata", {}).get("ended_at_ms"), 1025.0)


class NodeResultTimingMetadataTests(unittest.TestCase):
    def test_stamp_node_result_adds_timing_metadata(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        result = NodeResult(
            node_id="node-1",
            node_label="LLM",
            node_type="llm",
            status="success",
            output={},
            execution_time_ms=25.0,
            metadata={"invocation": "sub_agent_tool"},
        )

        with patch("app.services.workflow_executor.time.time", return_value=123.456):
            stamped = executor._stamp_node_result(result)

        self.assertEqual(stamped.metadata["sequence"], 1)
        self.assertEqual(stamped.metadata["invocation"], "sub_agent_tool")
        self.assertEqual(stamped.metadata["started_at_ms"], 123431.0)
        self.assertEqual(stamped.metadata["ended_at_ms"], 123456.0)

    def test_node_result_schema_keeps_metadata(self) -> None:
        schema = NodeResultSchema(
            node_id="node-1",
            node_label="LLM",
            node_type="llm",
            status="success",
            output={},
            execution_time_ms=12.5,
            metadata={"started_at_ms": 100.0, "ended_at_ms": 112.5},
        )

        self.assertEqual(schema.metadata["started_at_ms"], 100.0)
        self.assertEqual(schema.metadata["ended_at_ms"], 112.5)


class UpdateWorkflowSseConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_workflow_persists_sse_fields(self) -> None:
        current_user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=current_user.id,
            name="Workflow",
            description=None,
            nodes=[],
            edges=[],
            auth_type="jwt",
            auth_header_key=None,
            auth_header_value=None,
            webhook_body_mode="legacy",
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            sse_enabled=False,
            sse_node_config=None,
        )
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        expected_response = SimpleNamespace(
            sse_enabled=True,
            sse_node_config={"node-1": {"send_start": True, "start_message": "Custom start"}},
        )
        payload = WorkflowUpdate(
            sse_enabled=True,
            sse_node_config={"node-1": {"send_start": True, "start_message": "Custom start"}},
        )

        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch("app.api.workflows._build_workflow_response", return_value=expected_response),
        ):
            result = await update_workflow(
                workflow_id=workflow.id,
                workflow_data=payload,
                current_user=current_user,
                db=db,
            )

        self.assertTrue(workflow.sse_enabled)
        self.assertEqual(
            workflow.sse_node_config,
            {"node-1": {"send_start": True, "start_message": "Custom start"}},
        )
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(workflow)
        self.assertIs(result, expected_response)
