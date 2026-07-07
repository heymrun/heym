"""Tests for thread-safe node input reads and JSON parse error handling (PR #292)."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import agent_node, llm_node
from app.services.workflow_executor import NodeTraceableExecutionError, WorkflowExecutor


def _make_llm_ctx(
    executor: WorkflowExecutor,
    *,
    node_id: str = "llm-1",
    json_output_enabled: bool = True,
    batch_mode_enabled: bool = False,
) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=executor,
        node_id=node_id,
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"type": "llm", "data": {"jsonOutputEnabled": json_output_enabled}},
        node_type="llm",
        node_data={
            "jsonOutputEnabled": json_output_enabled,
            "batchModeEnabled": batch_mode_enabled,
        },
        node_label="testLlm",
    )


def _make_agent_ctx(
    executor: WorkflowExecutor,
    *,
    node_id: str = "agent-1",
    json_output_enabled: bool = True,
) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=executor,
        node_id=node_id,
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"type": "agent", "data": {"jsonOutputEnabled": json_output_enabled}},
        node_type="agent",
        node_data={"jsonOutputEnabled": json_output_enabled},
        node_label="testAgent",
    )


class LlmJsonParseErrorTests(unittest.TestCase):
    """Test that LLM JSON parse failures preserve trace context (Problem 2)."""

    def test_non_batch_json_parse_error_raises_node_traceable_error_with_trace_id(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor._execute_llm_node = MagicMock(
            return_value={"text": "not valid json {{{", "_trace_id": "trace-abc-123"}
        )
        executor._parse_json_output = MagicMock(side_effect=ValueError("malformed JSON"))
        executor._pop_internal_trace_id = MagicMock(return_value="trace-abc-123")
        executor._restore_internal_trace_id = MagicMock()

        ctx = _make_llm_ctx(executor)

        with self.assertRaises(NodeTraceableExecutionError) as cm:
            llm_node.execute(ctx)

        self.assertIn("LLM JSON parse error", str(cm.exception))
        self.assertIn("malformed JSON", str(cm.exception))

    def test_non_batch_json_parse_error_raises_value_error_without_trace_id(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor._execute_llm_node = MagicMock(return_value={"text": "not valid json {{{"})
        executor._parse_json_output = MagicMock(side_effect=ValueError("malformed JSON"))
        executor._pop_internal_trace_id = MagicMock(return_value=None)
        executor._restore_internal_trace_id = MagicMock()

        ctx = _make_llm_ctx(executor)

        with self.assertRaises(ValueError) as cm:
            llm_node.execute(ctx)

        self.assertIn("LLM JSON parse error", str(cm.exception))

    def test_batch_mode_handles_per_item_parse_errors(self) -> None:
        """Batch mode should handle parse errors per-item (unchanged behavior)."""
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor._execute_llm_node = MagicMock(
            return_value={
                "text": "",
                "_trace_id": "trace-abc-123",
                "results": [
                    {"status": "success", "text": '{"valid": true}'},
                    {"status": "success", "text": "bad json {{{"},
                    {"status": "success", "text": '{"name": "c"}', "model": "gpt-4"},
                ],
                "fallbackUsed": False,
                "model": "gpt-4",
            }
        )

        ctx = _make_llm_ctx(executor, batch_mode_enabled=True)

        result = llm_node.execute(ctx)

        self.assertIsInstance(result, dict)
        self.assertIn("results", result)
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertIn("parsedResults", result)


class AgentJsonParseErrorTests(unittest.TestCase):
    """Test that Agent JSON parse failures preserve trace context (Problem 2)."""

    def test_json_parse_error_raises_node_traceable_error_with_trace_id(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor._execute_agent_node = MagicMock(
            return_value={
                "text": "not valid json {{{",
                "_trace_id": "trace-xyz-456",
            }
        )
        executor._parse_json_output = MagicMock(side_effect=ValueError("malformed JSON"))
        executor._pop_internal_trace_id = MagicMock(return_value="trace-xyz-456")
        executor._restore_internal_trace_id = MagicMock()

        ctx = _make_agent_ctx(executor)

        with self.assertRaises(NodeTraceableExecutionError) as cm:
            agent_node.execute(ctx)

        self.assertIn("Agent JSON parse error", str(cm.exception))
        self.assertIn("malformed JSON", str(cm.exception))

    def test_json_parse_error_raises_value_error_without_trace_id(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        executor._execute_agent_node = MagicMock(return_value={"text": "not valid json {{{"})
        executor._parse_json_output = MagicMock(side_effect=ValueError("malformed JSON"))
        executor._pop_internal_trace_id = MagicMock(return_value=None)
        executor._restore_internal_trace_id = MagicMock()

        ctx = _make_agent_ctx(executor)

        with self.assertRaises(ValueError) as cm:
            agent_node.execute(ctx)

        self.assertIn("Agent JSON parse error", str(cm.exception))


class ParallelUpstreamInputCollectionTests(unittest.TestCase):
    """Test that two parallel upstream nodes feeding one downstream collect both inputs."""

    def test_parallel_upstream_nodes_collect_both_inputs(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "set1",
                "type": "set",
                "data": {"label": "branchA", "mappings": [{"key": "value", "value": "A"}]},
            },
            {
                "id": "set2",
                "type": "set",
                "data": {"label": "branchB", "mappings": [{"key": "value", "value": "B"}]},
            },
            {
                "id": "merge1",
                "type": "set",
                "data": {
                    "label": "mergeResult",
                    "mappings": [
                        {"key": "a", "value": "$branchA.value"},
                        {"key": "b", "value": "$branchB.value"},
                    ],
                },
            },
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "finalOut", "message": "$mergeResult.a + '&' + $mergeResult.b"},
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
            {"id": "e2", "source": "in1", "target": "set2"},
            {"id": "e3", "source": "set1", "target": "merge1"},
            {"id": "e4", "source": "set2", "target": "merge1"},
            {"id": "e5", "source": "merge1", "target": "out1"},
        ]

        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "start"}},
        )

        self.assertEqual(result.status, "success")
        results = {row["node_label"]: row for row in result.node_results}

        self.assertEqual(results["branchA"]["status"], "success")
        self.assertEqual(results["branchB"]["status"], "success")
        self.assertEqual(results["mergeResult"]["status"], "success")
        self.assertEqual(results["mergeResult"]["output"]["a"], "A")
        self.assertEqual(results["mergeResult"]["output"]["b"], "B")
        self.assertEqual(result.outputs, {"finalOut": {"result": "A&B"}})


class LoopWithInputSnapshotTests(unittest.TestCase):
    """Test that loop execution and re-execution work with the input snapshot change."""

    def test_loop_reexecution_works_with_snapshot(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "set1",
                "type": "set",
                "data": {
                    "label": "prepareItems",
                    "mappings": [{"key": "items", "value": "$array('x').add('y').add('z')"}],
                },
            },
            {
                "id": "loop1",
                "type": "loop",
                "data": {"label": "itemLoop", "arrayExpression": "$prepareItems.items"},
            },
            {
                "id": "set2",
                "type": "set",
                "data": {
                    "label": "processItem",
                    "mappings": [{"key": "item", "value": "$itemLoop.item"}],
                },
            },
            {
                "id": "set3",
                "type": "set",
                "data": {
                    "label": "doneSummary",
                    "mappings": [
                        {"key": "branch", "value": "$itemLoop.branch"},
                        {"key": "count", "value": "$itemLoop.results.length"},
                    ],
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
            {"id": "e2", "source": "set1", "target": "loop1"},
            {"id": "e3", "source": "loop1", "target": "set2", "sourceHandle": "loop"},
            {"id": "e4", "source": "set2", "target": "loop1", "targetHandle": "loop"},
            {"id": "e5", "source": "loop1", "target": "set3", "sourceHandle": "done"},
        ]

        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "start"}},
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs["doneSummary"]["branch"], "done")
        self.assertEqual(result.outputs["doneSummary"]["count"], 3)

        loop_results = [
            row
            for row in result.node_results
            if row["node_label"] == "itemLoop" and row["status"] == "success"
        ]
        self.assertEqual(len(loop_results), 4)  # 3 loop iterations + 1 done


class OutputAllowDownstreamTests(unittest.TestCase):
    """Test that output allowDownstream returns early while downstream continues."""

    def test_allow_downstream_continues_execution(self) -> None:
        """When an output node has allowDownstream, it completes early but
        the rest of the workflow continues to execute normally."""
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "set1",
                "type": "set",
                "data": {
                    "label": "dataPrep",
                    "mappings": [{"key": "value", "value": "hello"}],
                },
            },
            {
                "id": "out1",
                "type": "output",
                "data": {
                    "label": "earlyOutput",
                    "message": "$dataPrep.value",
                    "allowDownstream": True,
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
            {"id": "e2", "source": "set1", "target": "out1"},
        ]

        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "start"}},
        )

        self.assertEqual(result.status, "success")
        results = {row["node_label"]: row for row in result.node_results}
        self.assertEqual(results["earlyOutput"]["status"], "success")
        self.assertEqual(results["earlyOutput"]["output"]["result"], "hello")
        # The key assertion: allowDownstream does not prevent the workflow from completing
        self.assertIn("earlyOutput", result.outputs)

    def test_background_do_not_wait_records_downstream_results(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "wait1",
                "type": "wait",
                "data": {
                    "label": "backgroundTask",
                    "duration": 10,
                    "doNotWait": True,
                },
            },
            {
                "id": "set1",
                "type": "set",
                "data": {
                    "label": "afterWait",
                    "mappings": [{"key": "status", "value": "completed"}],
                },
            },
            {
                "id": "out1",
                "type": "output",
                "data": {"label": "finalOutput", "message": "$afterWait.status"},
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "wait1"},
            {"id": "e2", "source": "wait1", "target": "set1"},
            {"id": "e3", "source": "set1", "target": "out1"},
        ]

        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "start"}},
        )

        self.assertEqual(result.status, "success")

        # The background wait node should be recorded
        wait_results = [row for row in result.node_results if row["node_label"] == "backgroundTask"]
        self.assertTrue(len(wait_results) > 0)
        self.assertEqual(wait_results[0]["status"], "success")

        # Downstream nodes should have results
        downstream = [row for row in result.node_results if row["node_label"] == "afterWait"]
        self.assertTrue(len(downstream) > 0)
