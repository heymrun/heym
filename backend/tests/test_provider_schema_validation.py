import unittest

from jsonschema import SchemaError

from app.services.data_contracts import validate_json_schema, validate_provider_json_schema
from app.services.workflow_executor import WorkflowExecutor


class ProviderSchemaValidationTests(unittest.TestCase):
    def test_provider_schema_requires_object_root(self) -> None:
        with self.assertRaisesRegex(SchemaError, "root.*object"):
            validate_provider_json_schema({"type": "array", "items": {"type": "string"}})

    def test_provider_schema_requires_all_properties(self) -> None:
        with self.assertRaisesRegex(SchemaError, "required"):
            validate_provider_json_schema(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": [],
                }
            )

        with self.assertRaisesRegex(SchemaError, "required"):
            validate_provider_json_schema(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name", "name"],
                }
            )

    def test_provider_schema_rejects_explicit_additional_properties(self) -> None:
        with self.assertRaisesRegex(SchemaError, "additionalProperties"):
            validate_provider_json_schema(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": True,
                }
            )

        with self.assertRaisesRegex(SchemaError, "additionalProperties"):
            validate_provider_json_schema(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": {"type": "string"},
                }
            )

    def test_provider_schema_accepts_nullable_required_property(self) -> None:
        validate_provider_json_schema(
            {
                "type": "object",
                "properties": {"nickname": {"type": ["string", "null"]}},
                "required": ["nickname"],
            }
        )

    def test_unknown_format_is_rejected(self) -> None:
        with self.assertRaisesRegex(SchemaError, "format"):
            validate_json_schema(
                {
                    "type": "object",
                    "properties": {"value": {"type": "string", "format": "custom-heym"}},
                    "required": ["value"],
                }
            )

    def test_llm_schema_preflight_runs_before_guardrails(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        result = executor._execute_llm_node(
            credential_id="credential",
            node_id="llm",
            model="model",
            system_instruction=None,
            user_message="prompt",
            temperature=0.7,
            reasoning_effort=None,
            max_tokens=None,
            json_output_enabled=True,
            json_output_schema='{"type":"array"}',
            image_input=None,
            guardrails_config={"enabled": True},
        )

        self.assertIn("root", result["error"])

    def test_agent_schema_preflight_runs_before_guardrails(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        result = executor._execute_agent_node(
            node_id="agent",
            inputs={},
            node_data={
                "credentialId": "credential",
                "model": "model",
                "jsonOutputEnabled": True,
                "jsonOutputSchema": '{"type":"array"}',
            },
            guardrails_config={"enabled": True},
        )

        self.assertIn("root", result["error"])


if __name__ == "__main__":
    unittest.main()
