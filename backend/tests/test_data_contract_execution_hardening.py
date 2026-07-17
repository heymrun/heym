import time
import unittest
from unittest.mock import Mock, patch

from app.services.data_contracts import DataContractViolationError
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import llm_node
from app.services.workflow_executor import WorkflowExecutor


class DataContractExecutionHardeningTests(unittest.TestCase):
    def test_runtime_metadata_exclusion_is_limited_to_llm_and_agent(self) -> None:
        output = {"model": "business-value"}

        self.assertEqual(WorkflowExecutor._output_for_contract_validation(output, "set"), output)
        self.assertEqual(WorkflowExecutor._output_for_contract_validation(output, "llm"), {})

    def test_runtime_metadata_is_excluded_without_changing_final_output(self) -> None:
        runtime_metadata = {
            "model": "test-model",
            "fallbackUsed": True,
            "_generated_files": [{"id": "file-1"}],
        }
        for node_type in ("llm", "agent"):
            with self.subTest(node_type=node_type):
                output = {"answer": "ok", **runtime_metadata}
                executor = WorkflowExecutor(
                    nodes=[
                        {
                            "id": f"{node_type}1",
                            "type": node_type,
                            "data": {
                                "label": node_type,
                                "outputContract": {
                                    "type": "object",
                                    "required": ["answer"],
                                    "additionalProperties": False,
                                    "properties": {"answer": {"type": "string"}},
                                },
                            },
                        }
                    ],
                    edges=[],
                )

                with patch(
                    "app.services.workflow_executor.execute_node_handler", return_value=output
                ):
                    result = executor._execute_node_inner(f"{node_type}1", {})

                self.assertEqual(result.status, "success")
                self.assertEqual(result.output, output)
                self.assertEqual(output, {"answer": "ok", **runtime_metadata})

    def test_batch_json_output_raises_one_item_indexed_contract_error(self) -> None:
        executor = Mock()
        executor._visible_inputs.return_value = {}
        executor._resolve_template.return_value = "prompt"
        executor._execute_llm_node.return_value = {
            "results": [
                {"status": "success", "text": "not json"},
                {"status": "success", "text": '{"answer": 7}'},
            ],
            "model": "test-model",
        }
        executor._pop_internal_trace_id.return_value = None

        context = NodeExecutionContext(
            executor=executor,
            node_id="llm1",
            inputs={},
            allow_branch_skip=True,
            start_time=time.time(),
            node={"id": "llm1", "type": "llm", "data": {}},
            node_type="llm",
            node_data={
                "jsonOutputEnabled": True,
                "batchModeEnabled": True,
                "jsonOutputSchema": {
                    "type": "object",
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
            },
            node_label="batch llm",
        )

        with self.assertRaises(DataContractViolationError) as raised:
            llm_node.execute(context)

        self.assertEqual(raised.exception.node_label, "batch llm")
        self.assertEqual(len(raised.exception.errors), 2)
        self.assertTrue(raised.exception.errors[0].startswith("item[0]:"))
        self.assertTrue(raised.exception.errors[1].startswith("item[1]:"))

    def test_provider_failed_batch_item_fails_the_node(self) -> None:
        executor = Mock()
        executor._visible_inputs.return_value = {}
        executor._resolve_template.return_value = "prompt"
        executor._execute_llm_node.return_value = {
            "results": [
                {"status": "error", "error": "provider timeout"},
                {"status": "success", "text": '{"answer":"ok"}'},
            ],
            "model": "test-model",
        }
        executor._parse_json_output.return_value = {"answer": "ok"}
        executor._pop_internal_trace_id.return_value = None

        context = NodeExecutionContext(
            executor=executor,
            node_id="llm1",
            inputs={},
            allow_branch_skip=True,
            start_time=time.time(),
            node={"id": "llm1", "type": "llm", "data": {}},
            node_type="llm",
            node_data={
                "jsonOutputEnabled": True,
                "batchModeEnabled": True,
                "jsonOutputSchema": {
                    "type": "object",
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
            },
            node_label="batch llm",
        )

        with self.assertRaisesRegex(DataContractViolationError, r"item\[0\].*provider timeout"):
            llm_node.execute(context)

    def test_malformed_batch_item_fails_with_trace_id(self) -> None:
        executor = Mock()
        executor._visible_inputs.return_value = {}
        executor._resolve_template.return_value = "prompt"
        executor._execute_llm_node.return_value = {
            "results": [None],
            "model": "test-model",
            "_trace_id": "trace-123",
        }
        executor._pop_internal_trace_id.return_value = "trace-123"

        context = NodeExecutionContext(
            executor=executor,
            node_id="llm1",
            inputs={},
            allow_branch_skip=True,
            start_time=time.time(),
            node={"id": "llm1", "type": "llm", "data": {}},
            node_type="llm",
            node_data={"jsonOutputEnabled": True, "batchModeEnabled": True},
            node_label="batch llm",
        )

        with self.assertRaises(DataContractViolationError) as raised:
            llm_node.execute(context)

        self.assertEqual(raised.exception.trace_id, "trace-123")
        self.assertIn("malformed batch item", str(raised.exception))

    def test_empty_batch_fails_with_trace_id(self) -> None:
        executor = Mock()
        executor._visible_inputs.return_value = {}
        executor._resolve_template.return_value = "prompt"
        executor._execute_llm_node.return_value = {"results": [], "_trace_id": "trace-empty"}
        executor._pop_internal_trace_id.return_value = "trace-empty"

        context = NodeExecutionContext(
            executor=executor,
            node_id="llm1",
            inputs={},
            allow_branch_skip=True,
            start_time=time.time(),
            node={"id": "llm1", "type": "llm", "data": {}},
            node_type="llm",
            node_data={"jsonOutputEnabled": True, "batchModeEnabled": True},
            node_label="batch llm",
        )

        with self.assertRaisesRegex(DataContractViolationError, "no results") as raised:
            llm_node.execute(context)

        self.assertEqual(raised.exception.trace_id, "trace-empty")
