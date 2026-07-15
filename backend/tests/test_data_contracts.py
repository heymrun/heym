import unittest

from jsonschema import SchemaError

from app.services.data_contracts import (
    DataContractViolationError,
    parse_data_contract,
    validate_node_output,
)
from app.services.workflow_executor import WorkflowExecutor


class DataContractTests(unittest.TestCase):
    def test_executor_validates_configured_node_output(self) -> None:
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "set1",
                    "type": "set",
                    "data": {
                        "label": "payload",
                        "mappings": [{"key": "value", "value": "ok"}],
                        "outputContract": '{"type":"object","required":["value"]}',
                    },
                }
            ],
            edges=[],
        )
        result = executor.execute("workflow-contract-test", {})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.node_results[0]["metadata"]["data_contract"]["valid"], True)

    def test_executor_returns_contract_error_and_does_not_schedule_downstream(self) -> None:
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "set1",
                    "type": "set",
                    "data": {
                        "label": "payload",
                        "mappings": [{"key": "value", "value": "not-a-number"}],
                        "outputContract": '{"type":"object","properties":{"value":{"type":"number"}}}',
                    },
                },
                {
                    "id": "set2",
                    "type": "set",
                    "data": {"label": "downstream", "mappings": [{"key": "ran", "value": "yes"}]},
                },
            ],
            edges=[{"id": "edge", "source": "set1", "target": "set2"}],
        )
        result = executor.execute("workflow-contract-test", {})
        self.assertEqual(result.status, "error")
        failed = result.node_results[0]
        self.assertEqual(failed["metadata"]["data_contract"]["valid"], False)
        self.assertIn("number", failed["error"] or "")
        self.assertEqual(len(result.node_results), 1)

    def test_valid_output_is_accepted(self) -> None:
        validate_node_output(
            {"id": "abc", "count": 2},
            {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
            "result",
        )

    def test_invalid_output_has_path_and_metadata(self) -> None:
        with self.assertRaises(DataContractViolationError) as raised:
            validate_node_output(
                {"profile": {"age": "old"}},
                {
                    "type": "object",
                    "properties": {
                        "profile": {
                            "type": "object",
                            "required": ["age"],
                            "properties": {"age": {"type": "integer"}},
                        }
                    },
                },
                "user",
            )
        self.assertIn("profile.age", raised.exception.errors[0])
        self.assertIn("integer", str(raised.exception))

    def test_string_and_envelope_contracts_are_supported(self) -> None:
        contract = '{"schema": {"type": "array", "items": {"type": "string"}}}'
        self.assertEqual(
            parse_data_contract(contract), {"type": "array", "items": {"type": "string"}}
        )
        validate_node_output(["a", "b"], contract, "items")

    def test_invalid_contract_is_rejected(self) -> None:
        with self.assertRaises(SchemaError):
            validate_node_output({"value": 1}, {"type": "not-a-json-type"}, "result")
