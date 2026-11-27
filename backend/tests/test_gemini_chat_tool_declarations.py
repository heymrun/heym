"""Every tool the dashboard chat sends must be a declaration Gemini accepts.

Google answers 400 to the whole request for one bad declaration, so a single tool breaks Chat
on every OpenCode Gemini model.
"""

import json
import unittest
from typing import Any

from app.api.ai_assistant import DASHBOARD_CHAT_TOOLS
from app.services.llm_transport_gemini import GeminiTransport, _clean_schema


def _dangling_required(schema: Any, path: str = "") -> list[str]:
    if isinstance(schema, list):
        return [found for item in schema for found in _dangling_required(item, path)]
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    names = properties if isinstance(properties, dict) else {}
    found = [f"{path}.{name}" for name in schema.get("required") or [] if name not in names]
    for name, sub in names.items():
        found += _dangling_required(sub, f"{path}.{name}")
    for key in ("items", "anyOf"):
        if key in schema:
            found += _dangling_required(schema[key], f"{path}.{key}")
    return found


class TestChatToolsAsGeminiDeclarations(unittest.TestCase):
    def test_no_declaration_points_at_a_definition(self) -> None:
        for tool in DASHBOARD_CHAT_TOOLS:
            with self.subTest(tool=tool["function"]["name"]):
                parameters = GeminiTransport._translate_tool(tool)["parameters"]
                self.assertNotIn("$ref", json.dumps(parameters))

    def test_every_required_parameter_is_declared(self) -> None:
        for tool in DASHBOARD_CHAT_TOOLS:
            with self.subTest(tool=tool["function"]["name"]):
                parameters = GeminiTransport._translate_tool(tool)["parameters"]
                self.assertEqual(_dangling_required(parameters), [])

    def test_tools_without_references_are_only_cleaned(self) -> None:
        for tool in DASHBOARD_CHAT_TOOLS:
            source = tool["function"]["parameters"]
            if "$ref" in json.dumps(source):
                continue
            with self.subTest(tool=tool["function"]["name"]):
                self.assertEqual(
                    GeminiTransport._translate_tool(tool)["parameters"], _clean_schema(source)
                )


if __name__ == "__main__":
    unittest.main()
