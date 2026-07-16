"""Tests for thread-safe node input reads and JSON parse error handling (PR #292)."""

from __future__ import annotations

import time
import unittest
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import agent_node, llm_node
from app.services.workflow_executor import (
    NodeResult,
    NodeTraceableExecutionError,
    WorkflowExecutor,
    execute_workflow_streaming,
)

_ORIGINAL_EXECUTE_NODE_PARALLEL = WorkflowExecutor.execute_node_parallel


def _execute_node_parallel_with_slow_set(
    executor: WorkflowExecutor,
    node_id: str,
    inputs: dict,
    on_retry: Callable[[NodeResult, int, int], None] | None = None,
) -> NodeResult:
    if node_id == "node_1784204114120_is6kul2q1":
        time.sleep(0.02)
    return _ORIGINAL_EXECUTE_NODE_PARALLEL(executor, node_id, inputs, on_retry)


def _make_self_referential_loop_workflow() -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": "var_numbers",
            "type": "variable",
            "data": {
                "label": "createNumbers",
                "variableName": "numbers",
                "variableValue": "$array(1, 2, 3, 4, 5)",
                "variableType": "array",
            },
        },
        {
            "id": "loop_1",
            "type": "loop",
            "data": {"label": "processNumbers", "arrayExpression": "$vars.numbers"},
        },
        {
            "id": "output_done",
            "type": "output",
            "data": {"label": "finalOutput", "message": "Loop completed"},
        },
        {
            "id": "node_1784204114120_is6kul2q1",
            "type": "set",
            "data": {
                "label": "set",
                "mappings": [{"key": "num", "value": "$processNumbers.item"}],
            },
        },
    ]
    edges = [
        {"id": "edge_1", "source": "var_numbers", "target": "loop_1"},
        {
            "id": "edge_7",
            "source": "loop_1",
            "target": "output_done",
            "sourceHandle": "done",
        },
        {
            "id": "edge_loop_1_loop_1_1784204041004_1yec6",
            "source": "loop_1",
            "target": "loop_1",
            "sourceHandle": "loop",
            "targetHandle": "loop",
        },
        {
            "id": "edge_loop_1_node_1784204114120_is6kul2q1_1784204114120",
            "source": "loop_1",
            "target": "node_1784204114120_is6kul2q1",
            "sourceHandle": "loop",
            "targetHandle": "input",
        },
        {
            "id": "edge_node_1784204114120_is6kul2q1_loop_1_1784204141287",
            "source": "node_1784204114120_is6kul2q1",
            "target": "loop_1",
            "sourceHandle": "output",
            "targetHandle": "loop",
        },
    ]
    return nodes, edges


def _make_branched_loop_workflow() -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": "var_numbers",
            "type": "variable",
            "data": {
                "label": "createNumbers",
                "variableName": "numbers",
                "variableValue": "$array(1, 2, 3, 4, 5)",
                "variableType": "array",
            },
        },
        {
            "id": "loop_1",
            "type": "loop",
            "data": {"label": "processNumbers", "arrayExpression": "$vars.numbers"},
        },
        {
            "id": "condition_1",
            "type": "condition",
            "data": {"label": "checkIsThree", "condition": "$processNumbers.item == 3"},
        },
        {
            "id": "console_log",
            "type": "consoleLog",
            "data": {"label": "printNumber", "logMessage": "$processNumbers.item"},
        },
        {
            "id": "wait_1",
            "type": "wait",
            "data": {"label": "wait", "duration": 20},
        },
        {
            "id": "http_1",
            "type": "http",
            "data": {
                "label": "httpRequest",
                "curl": "curl -X GET https://example.test/$processNumbers.item",
                "onErrorEnabled": True,
            },
        },
        {
            "id": "output_done",
            "type": "output",
            "data": {"label": "finalOutput", "message": "Loop completed"},
        },
    ]
    edges = [
        {"id": "e1", "source": "var_numbers", "target": "loop_1"},
        {
            "id": "e2",
            "source": "loop_1",
            "target": "condition_1",
            "sourceHandle": "loop",
        },
        {
            "id": "e3",
            "source": "condition_1",
            "target": "console_log",
            "sourceHandle": "false",
        },
        {"id": "e4", "source": "console_log", "target": "wait_1"},
        {
            "id": "e5",
            "source": "wait_1",
            "target": "loop_1",
            "targetHandle": "loop",
        },
        {
            "id": "e6",
            "source": "condition_1",
            "target": "http_1",
            "sourceHandle": "true",
        },
        {
            "id": "e7",
            "source": "http_1",
            "target": "loop_1",
            "targetHandle": "loop",
        },
        {
            "id": "e8",
            "source": "loop_1",
            "target": "output_done",
            "sourceHandle": "done",
        },
    ]
    return nodes, edges


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


class LoopSelfEdgeExecutionTests(unittest.TestCase):
    """Verify visual self-edges cannot advance a loop ahead of its body."""

    def assert_sequential_loop_results(self, node_results: list[dict]) -> None:
        """Assert every body result completes before the following loop iteration."""
        loop_results = [
            row
            for row in node_results
            if row["node_label"] == "processNumbers" and row["status"] == "success"
        ]
        set_results = [
            row for row in node_results if row["node_label"] == "set" and row["status"] == "success"
        ]

        self.assertEqual(
            [row["output"].get("item") for row in loop_results[:-1]],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual([row["output"] for row in set_results], [{"num": i} for i in range(1, 6)])
        self.assertEqual(loop_results[-1]["output"]["branch"], "done")
        self.assertEqual(
            loop_results[-1]["output"]["results"],
            [{"num": i} for i in range(1, 6)],
        )

        for index, set_result in enumerate(set_results):
            self.assertLess(
                loop_results[index]["metadata"]["sequence"],
                set_result["metadata"]["sequence"],
            )
            self.assertLess(
                set_result["metadata"]["sequence"],
                loop_results[index + 1]["metadata"]["sequence"],
            )

    def test_loop_self_edge_does_not_skip_body_iterations(self) -> None:
        nodes, edges = _make_self_referential_loop_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        with patch.object(
            WorkflowExecutor,
            "execute_node_parallel",
            _execute_node_parallel_with_slow_set,
        ):
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs={})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"finalOutput": {"result": "Loop completed"}})
        self.assert_sequential_loop_results(result.node_results)

    def test_streaming_loop_self_edge_does_not_skip_body_iterations(self) -> None:
        nodes, edges = _make_self_referential_loop_workflow()

        with patch.object(
            WorkflowExecutor,
            "execute_node_parallel",
            _execute_node_parallel_with_slow_set,
        ):
            events = list(
                execute_workflow_streaming(
                    workflow_id=uuid.uuid4(),
                    nodes=nodes,
                    edges=edges,
                    inputs={},
                )
            )

        node_results = [
            {
                "node_label": event["node_label"],
                "status": event["status"],
                "output": event["output"],
                "metadata": event["metadata"],
            }
            for event in events
            if event.get("type") == "node_complete"
        ]
        execution_complete = next(
            event for event in events if event.get("type") == "execution_complete"
        )

        self.assertEqual(execution_complete["status"], "success")
        self.assertEqual(
            execution_complete["outputs"],
            {"finalOutput": {"result": "Loop completed"}},
        )
        self.assert_sequential_loop_results(node_results)


class LoopBranchExecutionTests(unittest.TestCase):
    """Verify each loop iteration waits for only its selected condition branch."""

    def _assert_branched_loop_results(self, node_results: list[dict]) -> None:
        loop_results = [
            row
            for row in node_results
            if row["node_label"] == "processNumbers" and row["status"] == "success"
        ]
        condition_results = [
            row
            for row in node_results
            if row["node_label"] == "checkIsThree" and row["status"] == "success"
        ]
        console_results = [
            row
            for row in node_results
            if row["node_label"] == "printNumber" and row["status"] == "success"
        ]
        wait_results = [
            row
            for row in node_results
            if row["node_label"] == "wait" and row["status"] == "success"
        ]
        http_results = [
            row
            for row in node_results
            if row["node_label"] == "httpRequest" and row["status"] == "success"
        ]

        self.assertEqual(
            [row["output"].get("item") for row in loop_results[:-1]],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(
            [row["output"]["branch"] for row in condition_results],
            ["false", "false", "true", "false", "false"],
        )
        self.assertEqual(
            [row["output"]["logMessage"] for row in console_results],
            [1, 2, 4, 5],
        )
        self.assertEqual(
            [row["output"]["logMessage"] for row in wait_results],
            [1, 2, 4, 5],
        )
        self.assertEqual(len(http_results), 1)
        if "request" in http_results[0]["output"]:
            self.assertEqual(http_results[0]["output"]["request"]["url"], "https://example.test/3")
        self.assertEqual(
            loop_results[-1]["output"]["results"],
            [
                {"branch": "false", "logMessage": 1},
                {"branch": "false", "logMessage": 2},
                http_results[0]["output"],
                {"branch": "false", "logMessage": 4},
                {"branch": "false", "logMessage": 5},
            ],
        )

        selected_branch_results = [
            wait_results[0],
            wait_results[1],
            http_results[0],
            wait_results[2],
            wait_results[3],
        ]
        for index, branch_result in enumerate(selected_branch_results):
            self.assertLess(
                loop_results[index]["metadata"]["sequence"],
                branch_result["metadata"]["sequence"],
            )
            self.assertLess(
                branch_result["metadata"]["sequence"],
                loop_results[index + 1]["metadata"]["sequence"],
            )

    @staticmethod
    def _mock_http_response(method: str, url: str, **_kwargs: object) -> httpx.Response:
        request = httpx.Request(method, url)
        return httpx.Response(200, json={"ok": True}, request=request)

    def test_loop_waits_for_selected_condition_branch(self) -> None:
        nodes, edges = _make_branched_loop_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        with patch("app.services.workflow_executor.get_http_client") as mock_get_client:
            mock_get_client.return_value.request.side_effect = self._mock_http_response
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs={})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"finalOutput": {"result": "Loop completed"}})
        self._assert_branched_loop_results(result.node_results)

    def test_loop_waits_for_selected_branch_when_http_returns_error_output(self) -> None:
        nodes, edges = _make_branched_loop_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)

        with patch("app.services.workflow_executor.get_http_client") as mock_get_client:
            mock_get_client.return_value.request.side_effect = httpx.ConnectError(
                "Name or service not known"
            )
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs={})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs, {"finalOutput": {"result": "Loop completed"}})
        self._assert_branched_loop_results(result.node_results)

        http_result = next(
            row
            for row in result.node_results
            if row["node_label"] == "httpRequest" and row["status"] == "success"
        )
        self.assertTrue(http_result["output"]["_errorBranch"])

    def test_streaming_loop_waits_for_selected_condition_branch(self) -> None:
        nodes, edges = _make_branched_loop_workflow()

        with patch("app.services.workflow_executor.get_http_client") as mock_get_client:
            mock_get_client.return_value.request.side_effect = self._mock_http_response
            events = list(
                execute_workflow_streaming(
                    workflow_id=uuid.uuid4(),
                    nodes=nodes,
                    edges=edges,
                    inputs={},
                )
            )

        node_results = [
            {
                "node_label": event["node_label"],
                "status": event["status"],
                "output": event["output"],
                "metadata": event["metadata"],
            }
            for event in events
            if event.get("type") == "node_complete"
        ]
        execution_complete = next(
            event for event in events if event.get("type") == "execution_complete"
        )

        self.assertEqual(execution_complete["status"], "success")
        self.assertEqual(
            execution_complete["outputs"],
            {"finalOutput": {"result": "Loop completed"}},
        )
        self._assert_branched_loop_results(node_results)


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
