import unittest
import uuid
from threading import Event
from unittest.mock import patch

from app.services.workflow_executor import NodeResult, WorkflowExecutor, execute_workflow_streaming


class _RetryingWorkflowExecutor(WorkflowExecutor):
    def __init__(self, nodes: list[dict], edges: list[dict]) -> None:
        super().__init__(nodes=nodes, edges=edges)
        self._attempts = 0

    def _execute_node_logic(
        self,
        node_id: str,
        inputs: dict,
        allow_branch_skip: bool,
        start_time: float,
        node: dict,
        node_type: str,
        node_data: dict,
        node_label: str,
    ) -> NodeResult:
        del inputs, allow_branch_skip, start_time, node, node_data
        self._attempts += 1
        if self._attempts == 1:
            raise RuntimeError("temporary failure")
        return NodeResult(
            node_id=node_id,
            node_label=node_label,
            node_type=node_type,
            status="success",
            output={"result": "ok"},
            execution_time_ms=18.0,
        )


class _FakeRetryStreamingExecutor:
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
        public_base_url: str = "",
    ) -> None:
        del (
            workflow_cache,
            test_mode,
            credentials_context,
            global_variables_context,
            workflow_id,
            trace_user_id,
            conversation_history,
            agent_progress_queue,
            public_base_url,
        )
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

    def _stamp_node_result(self, result: NodeResult) -> NodeResult:
        self._sequence += 1
        ended_at_ms = 1000.0 + (self._sequence * 50)
        result.metadata = {
            **dict(result.metadata or {}),
            "sequence": self._sequence,
            "started_at_ms": ended_at_ms - result.execution_time_ms,
            "ended_at_ms": ended_at_ms,
        }
        return result

    def execute_node_parallel(
        self,
        node_id: str,
        node_inputs: dict,
        on_retry: object | None = None,
    ) -> NodeResult:
        del node_inputs
        node = self.nodes[node_id]
        node_label = node.get("data", {}).get("label", node_id)

        retry_row = self._stamp_node_result(
            NodeResult(
                node_id=node_id,
                node_label=node_label,
                node_type=node.get("type", "unknown"),
                status="error",
                output={
                    "error": "temporary failure",
                    "message": "Attempt 1/3 failed. Retrying in 0s.",
                    "retry_attempt": 1,
                    "retry_max_attempts": 3,
                    "retry_wait_seconds": 0,
                },
                execution_time_ms=12.5,
                error="temporary failure",
                metadata={
                    "retry_stage": "attempt_failed",
                    "retry_attempt": 1,
                    "retry_max_attempts": 3,
                    "retry_wait_seconds": 0,
                },
            )
        )
        self.retry_node_results.append(retry_row)
        if on_retry:
            on_retry(retry_row, 2, 3)

        success_row = self._stamp_node_result(
            NodeResult(
                node_id=node_id,
                node_label=node_label,
                node_type=node.get("type", "unknown"),
                status="success",
                output={"result": "ok"},
                execution_time_ms=25.0,
            )
        )
        self.node_outputs[node_id] = success_row.output
        return success_row

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


class WorkflowRetryExecutionLogTests(unittest.TestCase):
    def test_execute_persists_retry_attempt_rows(self) -> None:
        executor = _RetryingWorkflowExecutor(
            nodes=[
                {
                    "id": "node-1",
                    "type": "http",
                    "data": {
                        "label": "Retry Node",
                        "retryEnabled": True,
                        "retryMaxAttempts": 2,
                        "retryWaitSeconds": 0,
                    },
                }
            ],
            edges=[],
        )

        with patch("app.services.workflow_executor.time.sleep", return_value=None):
            result = executor.execute(uuid.uuid4(), {})

        self.assertEqual(len(result.node_results), 2)

        retry_row = result.node_results[0]
        final_row = result.node_results[1]

        self.assertEqual(retry_row["status"], "error")
        self.assertEqual(retry_row["error"], "temporary failure")
        self.assertEqual(retry_row["metadata"]["retry_stage"], "attempt_failed")
        self.assertEqual(retry_row["metadata"]["retry_attempt"], 1)
        self.assertEqual(retry_row["metadata"]["retry_max_attempts"], 2)
        self.assertEqual(final_row["status"], "success")
        self.assertGreater(final_row["metadata"]["sequence"], retry_row["metadata"]["sequence"])

    def test_streaming_retry_event_carries_retry_result_and_history_row(self) -> None:
        nodes = [{"id": "node-1", "type": "llm", "data": {"label": "Retry LLM"}}]

        with patch("app.services.workflow_executor.WorkflowExecutor", _FakeRetryStreamingExecutor):
            events = list(
                execute_workflow_streaming(
                    workflow_id=uuid.uuid4(),
                    nodes=nodes,
                    edges=[],
                    inputs={},
                    cancel_event=Event(),
                )
            )

        retry_event = next(event for event in events if event.get("type") == "node_retry")
        completion_event = next(
            event for event in events if event.get("type") == "execution_complete"
        )

        self.assertEqual(retry_event["attempt"], 2)
        self.assertEqual(retry_event["retry_result"]["metadata"]["retry_stage"], "attempt_failed")
        self.assertEqual(retry_event["retry_result"]["metadata"]["retry_attempt"], 1)

        self.assertEqual(len(completion_event["node_results"]), 2)
        self.assertEqual(
            completion_event["node_results"][0]["metadata"]["retry_stage"], "attempt_failed"
        )
        self.assertEqual(completion_event["node_results"][1]["status"], "success")
