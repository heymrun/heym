import json
import unittest

from jsonschema import SchemaError

from app.api.ai_assistant import _workflow_schema_error_response


class AIAssistantSchemaValidationTests(unittest.TestCase):
    def test_schema_validation_errors_have_422_tool_semantics(self) -> None:
        payload = json.loads(_workflow_schema_error_response(SchemaError("bad schema")))

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["status_code"], 422)
        self.assertEqual(payload["detail"], "bad schema")
        self.assertEqual(payload["error"], "bad schema")
