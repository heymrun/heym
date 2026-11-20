"""Tests for Execute node failing when its sub-workflow fails (#1069)."""

import time
import unittest
import unittest.mock
import uuid

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.execute_node import execute as execute_node
from app.services.workflow_executor import (
    ExecutionResult,
    WorkflowCancelledError,
    WorkflowExecutor,
)

_START = {
    "id": "start",
    "type": "textInput",
    "position": {"x": 0, "y": 0},
    "data": {"label": "start", "inputFields": [{"key": "text"}]},
}


class ExecuteSubworkflowFailureTests(unittest.TestCase):
    def test_subworkflow_node_failure_fails_execute_node_and_marks_run_red(self) -> None:
        child_id = str(uuid.uuid4())
        child_wf = {
            "nodes": [
                _START,
                {
                    "id": "code_err",
                    "type": "code",
                    "position": {"x": 300, "y": 0},
                    "data": {
                        "label": "brokenCode",
                        "codeSource": "",
                    },
                },
            ],
            "edges": [{"id": "ce1", "source": "start", "target": "code_err"}],
            "name": "FailingChild",
            "input_fields": [],
        }

        parent_call = {
            "id": "call_child",
            "type": "execute",
            "position": {"x": 300, "y": 0},
            "data": {
                "label": "callChild",
                "executeWorkflowId": child_id,
                "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
            },
        }
        downstream_output = {
            "id": "out",
            "type": "output",
            "position": {"x": 600, "y": 0},
            "data": {
                "label": "finalOutput",
                "outputSchema": [{"key": "data", "value": "$callChild.outputs"}],
            },
        }

        executor = WorkflowExecutor(
            nodes=[_START, parent_call, downstream_output],
            edges=[
                {"id": "e1", "source": "start", "target": "call_child"},
                {"id": "e2", "source": "call_child", "target": "out"},
            ],
            workflow_cache={child_id: child_wf},
        )
        res = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )

        self.assertEqual(res.status, "error")
        parent_row = next(r for r in res.node_results if r["node_label"] == "callChild")
        self.assertEqual(parent_row["status"], "error")
        self.assertIn("Code is empty", parent_row["error"])
        # Downstream node must not have executed
        self.assertFalse(any(r["node_label"] == "finalOutput" for r in res.node_results))
        # The parent run output reflects the failure
        self.assertIn("Code is empty", str(res.outputs.get("error", "")))
        # SubWorkflowExecution is still captured in trace
        self.assertEqual(len(res.sub_workflow_executions), 1)
        self.assertEqual(res.sub_workflow_executions[0].status, "error")

    def test_subworkflow_failure_with_on_error_enabled_routes_to_error_branch(self) -> None:
        child_id = str(uuid.uuid4())
        child_wf = {
            "nodes": [
                _START,
                {
                    "id": "code_err",
                    "type": "code",
                    "position": {"x": 300, "y": 0},
                    "data": {
                        "label": "brokenCode",
                        "codeSource": "",
                    },
                },
            ],
            "edges": [{"id": "ce1", "source": "start", "target": "code_err"}],
            "name": "FailingChild",
            "input_fields": [],
        }

        parent_call = {
            "id": "call_child",
            "type": "execute",
            "position": {"x": 300, "y": 0},
            "data": {
                "label": "callChild",
                "executeWorkflowId": child_id,
                "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
                "onErrorEnabled": True,
            },
        }
        error_handler = {
            "id": "handle_err",
            "type": "set",
            "position": {"x": 600, "y": 100},
            "data": {
                "label": "catchError",
                "mappings": [{"key": "caught", "value": "$callChild.error"}],
            },
        }
        normal_downstream = {
            "id": "normal_out",
            "type": "set",
            "position": {"x": 600, "y": -100},
            "data": {
                "label": "happyPath",
                "mappings": [{"key": "val", "value": "should_not_run"}],
            },
        }

        executor = WorkflowExecutor(
            nodes=[_START, parent_call, error_handler, normal_downstream],
            edges=[
                {"id": "e1", "source": "start", "target": "call_child"},
                {
                    "id": "e2",
                    "source": "call_child",
                    "target": "handle_err",
                    "sourceHandle": "error",
                },
                {"id": "e3", "source": "call_child", "target": "normal_out"},
            ],
            workflow_cache={child_id: child_wf},
        )
        res = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )

        self.assertEqual(res.status, "success")
        parent_row = next(r for r in res.node_results if r["node_label"] == "callChild")
        self.assertEqual(parent_row["status"], "success")
        self.assertTrue(parent_row["output"].get("_errorBranch"))
        self.assertIn("Code is empty", parent_row["output"].get("error", ""))

        caught_row = next((r for r in res.node_results if r["node_label"] == "catchError"), None)
        self.assertIsNotNone(caught_row)
        assert caught_row is not None
        self.assertIn("Code is empty", caught_row["output"].get("caught", ""))

        # Happy path node was skipped
        happy_row = next((r for r in res.node_results if r["node_label"] == "happyPath"), None)
        self.assertIsNotNone(happy_row)
        assert happy_row is not None
        self.assertEqual(happy_row["status"], "skipped")

    def test_nested_subworkflow_failure_propagates_to_top_level_run(self) -> None:
        c_id = str(uuid.uuid4())
        b_id = str(uuid.uuid4())

        c_wf = {
            "nodes": [
                _START,
                {
                    "id": "c_err",
                    "type": "code",
                    "position": {"x": 300, "y": 0},
                    "data": {
                        "label": "cCode",
                        "codeSource": "",
                    },
                },
            ],
            "edges": [{"id": "ce1", "source": "start", "target": "c_err"}],
            "name": "WorkflowC",
            "input_fields": [],
        }

        b_wf = {
            "nodes": [
                _START,
                {
                    "id": "b_call_c",
                    "type": "execute",
                    "position": {"x": 300, "y": 0},
                    "data": {
                        "label": "callC",
                        "executeWorkflowId": c_id,
                        "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
                    },
                },
            ],
            "edges": [{"id": "be1", "source": "start", "target": "b_call_c"}],
            "name": "WorkflowB",
            "input_fields": [],
        }

        a_call_b = {
            "id": "a_call_b",
            "type": "execute",
            "position": {"x": 300, "y": 0},
            "data": {
                "label": "callB",
                "executeWorkflowId": b_id,
                "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
            },
        }

        executor = WorkflowExecutor(
            nodes=[_START, a_call_b],
            edges=[{"id": "ae1", "source": "start", "target": "a_call_b"}],
            workflow_cache={b_id: b_wf, c_id: c_wf},
        )
        res = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )

        self.assertEqual(res.status, "error")
        a_row = next(r for r in res.node_results if r["node_label"] == "callB")
        self.assertEqual(a_row["status"], "error")
        self.assertIn("Code is empty", a_row["error"])
        self.assertIn("Code is empty", str(res.outputs.get("error", "")))

    def test_subworkflow_success_returns_expected_outputs(self) -> None:
        child_id = str(uuid.uuid4())
        child_wf = {
            "nodes": [
                _START,
                {
                    "id": "set_ok",
                    "type": "set",
                    "position": {"x": 300, "y": 0},
                    "data": {
                        "label": "echo",
                        "mappings": [{"key": "reply", "value": "$start.body.text"}],
                    },
                },
            ],
            "edges": [{"id": "ce1", "source": "start", "target": "set_ok"}],
            "name": "EchoChild",
            "input_fields": [],
        }

        parent_call = {
            "id": "call_child",
            "type": "execute",
            "position": {"x": 300, "y": 0},
            "data": {
                "label": "callChild",
                "executeWorkflowId": child_id,
                "executeInputMappings": [{"key": "text", "value": "$start.body.text"}],
            },
        }

        executor = WorkflowExecutor(
            nodes=[_START, parent_call],
            edges=[{"id": "e1", "source": "start", "target": "call_child"}],
            workflow_cache={child_id: child_wf},
        )
        res = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hello"}},
        )

        self.assertEqual(res.status, "success")
        parent_row = next(r for r in res.node_results if r["node_label"] == "callChild")
        self.assertEqual(parent_row["status"], "success")
        self.assertEqual(parent_row["output"]["status"], "success")
        self.assertEqual(parent_row["output"]["outputs"], {"echo": {"reply": "hello"}})

    def test_cancelled_subworkflow_raises_workflow_cancelled_error(self) -> None:
        child_id = str(uuid.uuid4())
        parent_id = uuid.uuid4()
        parent = WorkflowExecutor(
            nodes=[],
            edges=[],
            workflow_cache={
                child_id: {
                    "name": "Target",
                    "nodes": [_START],
                    "edges": [],
                }
            },
            workflow_id=parent_id,
        )
        ctx = NodeExecutionContext(
            executor=parent,
            node_id="execute",
            inputs={},
            allow_branch_skip=False,
            start_time=time.time(),
            node={
                "id": "execute",
                "type": "execute",
                "data": {"executeWorkflowId": child_id},
            },
            node_type="execute",
            node_data={"executeWorkflowId": child_id},
            node_label="Execute",
        )

        cancelled_result = ExecutionResult(
            workflow_id=uuid.UUID(child_id),
            status="cancelled",
            outputs={"error": "Cancelled by user"},
            execution_time_ms=5.0,
            node_results=[],
        )

        with unittest.mock.patch.object(WorkflowExecutor, "execute", return_value=cancelled_result):
            with self.assertRaises(WorkflowCancelledError) as ctx_err:
                execute_node(ctx)
            self.assertIn("Cancelled by user", str(ctx_err.exception))


if __name__ == "__main__":
    unittest.main()
