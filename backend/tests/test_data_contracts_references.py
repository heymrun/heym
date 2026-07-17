import unittest

from jsonschema import SchemaError

from app.services.data_contracts import (
    DataContractViolationError,
    validate_json_schema,
    validate_node_output,
)


class DataContractReferenceTests(unittest.TestCase):
    def test_missing_local_reference_raises_schema_error_with_context(self) -> None:
        schema = {
            "$ref": "#/$defs/missing",
            "$defs": {},
        }

        with self.assertRaisesRegex(
            SchemaError,
            r"Output contract.*#/\$defs/missing",
        ):
            validate_json_schema(schema, field_name="Output contract")

    def test_valid_local_reference_is_resolved_against_submitted_schema(self) -> None:
        schema = {
            "$ref": "#/$defs/payload",
            "$defs": {
                "payload": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "string"}},
                }
            },
        }

        validate_node_output({"value": "ok"}, schema, "result")

        with self.assertRaisesRegex(DataContractViolationError, "value"):
            validate_node_output({}, schema, "result")

    def test_local_reference_uses_nested_id_scope(self) -> None:
        schema = {
            "$defs": {
                "child": {
                    "$id": "child",
                    "$defs": {"value": {"type": "object", "required": ["value"]}},
                    "$ref": "#/$defs/value",
                }
            },
            "$ref": "#/$defs/child",
        }

        validate_node_output({"value": "ok"}, schema, "result")
