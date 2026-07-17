import pickle
import time
import unittest
from unittest.mock import Mock, patch

from jsonschema import SchemaError

from app.services.data_contracts import (
    MAX_VALIDATION_ERRORS,
    DataContractViolationError,
    parse_data_contract,
    validate_json_output,
    validate_json_schema,
    validate_node_output,
    validate_provider_json_schema,
    validate_workflow_node_schemas,
)
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import agent_node, llm_node
from app.services.workflow_executor import WorkflowExecutor, _ensure_additional_properties


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

    def test_unknown_schema_keywords_are_rejected(self) -> None:
        with self.assertRaisesRegex(SchemaError, "unsupported keyword.*foo"):
            validate_json_schema({"type": "object", "foo": True})

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

    def test_internal_control_fields_do_not_break_strict_contracts(self) -> None:
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "condition1",
                    "type": "condition",
                    "data": {
                        "label": "condition",
                        "condition": "true",
                        "outputContract": (
                            '{"type":"object","required":["branch"],'
                            '"additionalProperties":false,"properties":{"branch":{"type":"string"}}}'
                        ),
                    },
                }
            ],
            edges=[],
        )
        result = executor.execute("workflow-contract-test", {})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.node_results[0]["output"], {"branch": "true"})

    def test_schema_errors_are_not_retried(self) -> None:
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "set1",
                    "type": "set",
                    "data": {
                        "label": "payload",
                        "retryEnabled": True,
                        "retryMaxAttempts": 3,
                        "retryWaitSeconds": 0,
                    },
                }
            ],
            edges=[],
        )
        retry_callback = Mock()
        with patch.object(
            executor, "_execute_node_logic", side_effect=SchemaError("invalid")
        ) as logic:
            result = executor._execute_node_inner("set1", {}, on_retry=retry_callback)
        self.assertEqual(logic.call_count, 1)
        retry_callback.assert_not_called()
        self.assertEqual(result.status, "error")

    def test_schema_error_exposes_data_contract_failure_metadata(self) -> None:
        executor = WorkflowExecutor(
            nodes=[
                {
                    "id": "set1",
                    "type": "set",
                    "data": {
                        "label": "payload",
                        "mappings": [{"key": "value", "value": "ok"}],
                        "outputContract": ('{"$ref":"#/$defs/missing","$defs":{}}'),
                    },
                }
            ],
            edges=[],
        )

        result = executor.execute("workflow-contract-schema-error-test", {})

        metadata = result.node_results[0]["metadata"]["data_contract"]
        self.assertFalse(metadata["valid"])
        self.assertTrue(metadata["errors"])

    def test_contract_error_with_no_details_is_safe_to_string_and_pickle(self) -> None:
        error = DataContractViolationError(node_label="payload", errors=())
        self.assertIn("unknown validation error", str(error))
        restored = pickle.loads(pickle.dumps(error))
        self.assertEqual(restored.node_label, "payload")
        self.assertEqual(restored.errors, ())

    def test_string_and_envelope_contracts_are_supported(self) -> None:
        contract = '{"schema": {"type": "array", "items": {"type": "string"}}}'
        self.assertEqual(
            parse_data_contract(contract), {"type": "array", "items": {"type": "string"}}
        )
        validate_node_output(["a", "b"], contract, "items")

    def test_invalid_envelope_schema_is_rejected(self) -> None:
        with self.assertRaisesRegex(SchemaError, "schema.*object"):
            validate_node_output({"value": 1}, {"schema": "not-a-schema"}, "result")

    def test_output_contract_does_not_unwrap_schema_sibling(self) -> None:
        validate_node_output(
            {"schema": "ok"},
            {
                "type": "object",
                "required": ["schema"],
                "properties": {"schema": {"type": "string"}},
            },
            "result",
        )

    def test_json_output_schema_rejects_provider_envelope(self) -> None:
        with self.assertRaisesRegex(SchemaError, "envelope"):
            validate_json_schema(
                '{"name":"output","schema":{"type":"string"}}',
                field_name="JSON output schema",
            )

    def test_json_output_schema_validates_array_instances(self) -> None:
        validate_json_output(
            ["a", "b"],
            '{"type":"array","items":{"type":"string"}}',
            "result",
        )
        with self.assertRaises(DataContractViolationError):
            validate_json_output(
                ["a", 1],
                '{"type":"array","items":{"type":"string"}}',
                "result",
            )

    def test_llm_json_output_must_match_json_output_schema(self) -> None:
        executor = Mock()
        executor._visible_inputs.return_value = {}
        executor._resolve_template.return_value = "prompt"
        executor._execute_llm_node.return_value = {
            "text": '{"count":"not-a-number"}',
            "model": "test-model",
        }
        executor._pop_internal_trace_id.return_value = "trace-llm-contract"

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
                "jsonOutputSchema": (
                    '{"type":"object","required":["count"],'
                    '"properties":{"count":{"type":"number"}}}'
                ),
            },
            node_label="llm",
        )

        with self.assertRaises(DataContractViolationError) as raised:
            llm_node.execute(context)
        self.assertEqual(raised.exception.trace_id, "trace-llm-contract")

    def test_agent_json_output_must_match_json_output_schema(self) -> None:
        executor = Mock()
        executor._execute_agent_node.return_value = {
            "text": '{"status":"unknown"}',
            "model": "test-model",
        }
        executor._pop_internal_trace_id.return_value = "trace-agent-contract"

        context = NodeExecutionContext(
            executor=executor,
            node_id="agent1",
            inputs={},
            allow_branch_skip=True,
            start_time=time.time(),
            node={"id": "agent1", "type": "agent", "data": {}},
            node_type="agent",
            node_data={
                "jsonOutputEnabled": True,
                "jsonOutputSchema": (
                    '{"type":"object","required":["status"],'
                    '"properties":{"status":{"type":"string",'
                    '"enum":["ok","error"]}}}'
                ),
            },
            node_label="agent",
        )

        with self.assertRaises(DataContractViolationError) as raised:
            agent_node.execute(context)
        self.assertEqual(raised.exception.trace_id, "trace-agent-contract")

    def test_invalid_contract_is_rejected(self) -> None:
        with self.assertRaises(SchemaError):
            validate_node_output({"value": 1}, {"type": "not-a-json-type"}, "result")

    def test_format_assertions_are_checked(self) -> None:
        with self.assertRaises(DataContractViolationError):
            validate_node_output(
                {"email": "not-an-email"},
                {"type": "object", "properties": {"email": {"format": "email"}}},
                "result",
            )

    def test_extended_format_assertions_are_checked(self) -> None:
        for schema, value in (
            ({"type": "string", "format": "date-time"}, "2026-07-17 12:00:00"),
            ({"type": "string", "format": "uri"}, "not a uri"),
            ({"type": "string", "format": "duration"}, "not a duration"),
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(DataContractViolationError):
                    validate_node_output(value, schema, "formatted")

    def test_malformed_uri_is_reported_as_contract_violation(self) -> None:
        with self.assertRaises(DataContractViolationError):
            validate_node_output(
                "http://[bad",
                {"type": "string", "format": "uri"},
                "formatted",
            )

    def test_valid_hostname_and_relative_json_pointer_are_accepted(self) -> None:
        validate_node_output("example.com", {"type": "string", "format": "hostname"}, "formatted")
        validate_node_output(
            "1/foo", {"type": "string", "format": "relative-json-pointer"}, "formatted"
        )

    def test_schema_complexity_limits_are_enforced(self) -> None:
        with self.assertRaisesRegex(SchemaError, "pattern length"):
            validate_json_schema({"type": "string", "pattern": "x" * 5000})

        with self.assertRaisesRegex(SchemaError, "patternProperties key length"):
            validate_json_schema(
                {"type": "object", "patternProperties": {"x" * 5000: {"type": "string"}}}
            )

    def test_schema_vocabulary_is_loaded_from_package_local_copy(self) -> None:
        import json
        from pathlib import Path

        from app.services import data_contracts as dc

        shared_path = Path(__file__).resolve().parents[2] / "shared" / "json-schema-vocabulary.json"
        self.assertEqual(
            dc._VOCABULARY_PATH,
            Path(dc.__file__).resolve().parent / "json_schema_vocabulary.json",
        )
        self.assertTrue(dc._VOCABULARY_PATH.is_file())
        self.assertTrue(shared_path.is_file())
        with shared_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        with dc._VOCABULARY_PATH.open(encoding="utf-8") as handle:
            packaged = json.load(handle)
        self.assertEqual(packaged, payload)
        self.assertEqual(dc._SUPPORTED_SCHEMA_KEYWORDS, frozenset(payload["keywords"]))
        self.assertEqual(dc._SUPPORTED_FORMATS, frozenset(payload["formats"]))
        self.assertIn("type", dc._SUPPORTED_SCHEMA_KEYWORDS)
        self.assertIn("email", dc._SUPPORTED_FORMATS)

    def test_ensure_additional_properties_ignores_legacy_definitions(self) -> None:
        schema = _ensure_additional_properties(
            {
                "type": "object",
                "definitions": {
                    "inner": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    }
                },
            }
        )
        self.assertNotIn("additionalProperties", schema["definitions"]["inner"])

    def test_provider_capabilities_are_explicit_and_strict_by_default(self) -> None:
        with self.assertRaisesRegex(SchemaError, "root must be an object"):
            validate_provider_json_schema({"type": "array"})

    def test_external_refs_are_rejected(self) -> None:
        with self.assertRaisesRegex(SchemaError, "local \\$ref"):
            validate_json_schema({"$ref": "https://example.com/schema.json"})

    def test_absolute_schema_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(SchemaError, "local \\$id"):
            validate_json_schema({"$id": "https://example.com/schema.json", "type": "object"})

    def test_date_time_without_timezone_is_accepted(self) -> None:
        validate_node_output(
            "2020-01-01T00:00:00",
            {"type": "string", "format": "date-time"},
            "timestamp",
        )

    def test_external_dynamic_and_recursive_refs_are_rejected(self) -> None:
        for keyword in ("$dynamicRef", "$recursiveRef"):
            with self.subTest(keyword=keyword), self.assertRaisesRegex(SchemaError, "local"):
                validate_json_schema({keyword: "https://example.com/schema.json"})

    def test_local_refs_still_validate_without_remote_retrieval(self) -> None:
        validate_node_output(
            {"value": "ok"},
            {
                "$defs": {"value": {"type": "object", "required": ["value"]}},
                "$ref": "#/$defs/value",
            },
            "result",
        )

    def test_strict_schema_recurses_through_single_schema_keywords(self) -> None:
        schema = _ensure_additional_properties(
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
                "if": {
                    "type": "object",
                    "properties": {"kind": {"type": "string"}},
                },
                "then": {
                    "type": "object",
                    "properties": {"result": {"type": "number"}},
                },
            }
        )
        self.assertIs(schema["items"]["additionalProperties"], False)
        self.assertIs(schema["if"]["additionalProperties"], False)
        self.assertIs(schema["then"]["additionalProperties"], False)

    def test_workflow_schema_fields_are_validated_before_persisting(self) -> None:
        with self.assertRaisesRegex(SchemaError, "payload"):
            validate_workflow_node_schemas(
                [
                    {
                        "id": "set1",
                        "data": {"label": "payload", "outputContract": "{invalid"},
                    }
                ]
            )

    def test_persisted_json_output_schema_rejects_provider_envelope(self) -> None:
        with self.assertRaisesRegex(SchemaError, "JSON output schema.*envelope"):
            validate_workflow_node_schemas(
                [
                    {
                        "id": "llm1",
                        "data": {
                            "label": "llm",
                            "jsonOutputSchema": ('{"name":"output","schema":{"type":"string"}}'),
                        },
                    }
                ]
            )

    def test_persisted_enabled_json_output_schema_uses_provider_constraints(self) -> None:
        with self.assertRaisesRegex(
            SchemaError, r"JSON output schema for 'llm'.*root must be an object"
        ):
            validate_workflow_node_schemas(
                [
                    {
                        "id": "llm1",
                        "data": {
                            "label": "llm",
                            "jsonOutputEnabled": True,
                            "jsonOutputSchema": {"type": "array"},
                        },
                    }
                ]
            )

    def test_contract_validation_preserves_array_outputs(self) -> None:
        output = ["a", "b"]
        self.assertEqual(WorkflowExecutor._output_for_contract_validation(output), output)

    def test_validation_errors_are_bounded(self) -> None:
        schema = {
            "type": "object",
            "required": [f"field{index}" for index in range(MAX_VALIDATION_ERRORS + 5)],
        }
        with self.assertRaises(DataContractViolationError) as raised:
            validate_node_output({}, schema, "result")
        self.assertEqual(len(raised.exception.errors), MAX_VALIDATION_ERRORS)
