"""Unit tests for pure helper functions in app.api.workflows."""

import json
import unittest
from types import SimpleNamespace

from app.api.workflows import (
    _coerce_bool,
    _sanitize_headers,
    _sanitize_invalid_unicode,
    extract_input_fields_from_workflow,
    extract_output_node_from_workflow,
    get_first_node_type,
    get_node_output_expression,
)


def _safe_json_parse(value: str | None) -> str | None:
    """Safely parse JSON string, handling errors gracefully."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _workflow(nodes=None, edges=None):
    """Return a lightweight stand-in for a Workflow ORM object."""
    return SimpleNamespace(nodes=nodes or [], edges=edges or [])


class CoerceBoolTests(unittest.TestCase):
    def test_true_bool_passthrough(self) -> None:
        self.assertTrue(_coerce_bool(True))

    def test_false_bool_passthrough(self) -> None:
        self.assertFalse(_coerce_bool(False))

    def test_none_returns_false(self) -> None:
        self.assertFalse(_coerce_bool(None))

    def test_string_true_variants(self) -> None:
        for value in ("1", "true", "True", "TRUE", "yes", "Yes", "on", "On"):
            with self.subTest(value=value):
                self.assertTrue(_coerce_bool(value))

    def test_string_false_variants(self) -> None:
        for value in ("0", "false", "no", "off", "", "anything"):
            with self.subTest(value=value):
                self.assertFalse(_coerce_bool(value))

    def test_whitespace_is_stripped(self) -> None:
        self.assertTrue(_coerce_bool("  true  "))


class SanitizeHeadersTests(unittest.TestCase):
    def test_removes_authorization_header(self) -> None:
        result = _sanitize_headers(
            {"Authorization": "Bearer token", "content-type": "application/json"}
        )
        self.assertNotIn("authorization", result)
        self.assertIn("content-type", result)

    def test_lowercases_keys(self) -> None:
        result = _sanitize_headers({"Content-Type": "text/plain"})
        self.assertIn("content-type", result)
        self.assertNotIn("Content-Type", result)

    def test_removes_all_sensitive_headers(self) -> None:
        sensitive = {
            "authorization": "x",
            "cookie": "y",
            "set-cookie": "z",
            "x-execution-token": "a",
            "x-mcp-key": "b",
            "proxy-authorization": "c",
            "x-api-key": "d",
            "x-auth-token": "e",
            "x-csrf-token": "f",
            "x-session-token": "g",
        }
        result = _sanitize_headers(sensitive)
        self.assertEqual(result, {})

    def test_empty_headers(self) -> None:
        self.assertEqual(_sanitize_headers({}), {})

    def test_preserves_safe_headers(self) -> None:
        result = _sanitize_headers({"accept": "application/json", "x-request-id": "abc"})
        self.assertEqual(result, {"accept": "application/json", "x-request-id": "abc"})


class SanitizeInvalidUnicodeTests(unittest.TestCase):
    def test_regular_string_unchanged(self) -> None:
        self.assertEqual(_sanitize_invalid_unicode("hello"), "hello")

    def test_surrogate_replaced_with_replacement_char(self) -> None:
        surrogate = "\ud800"
        result = _sanitize_invalid_unicode(surrogate)
        self.assertEqual(result, "\ufffd")

    def test_list_items_sanitized(self) -> None:
        result = _sanitize_invalid_unicode(["\ud800", "ok"])
        self.assertEqual(result, ["\ufffd", "ok"])

    def test_dict_values_sanitized(self) -> None:
        result = _sanitize_invalid_unicode({"key": "\ud83d"})
        self.assertEqual(result, {"key": "\ufffd"})

    def test_dict_keys_sanitized(self) -> None:
        result = _sanitize_invalid_unicode({"\udcff": "value"})
        self.assertEqual(result, {"\ufffd": "value"})

    def test_non_string_passthrough(self) -> None:
        self.assertEqual(_sanitize_invalid_unicode(42), 42)
        self.assertIsNone(_sanitize_invalid_unicode(None))


class ExtractInputFieldsTests(unittest.TestCase):
    def _make_text_input_node(self, node_id: str, fields=None, active=True) -> dict:
        return {
            "id": node_id,
            "type": "textInput",
            "data": {
                "active": active,
                "inputFields": fields or [{"key": "text"}],
            },
        }

    def test_returns_empty_for_no_nodes(self) -> None:
        wf = _workflow()
        self.assertEqual(extract_input_fields_from_workflow(wf), [])

    def test_root_text_input_node_extracted(self) -> None:
        wf = _workflow(
            nodes=[self._make_text_input_node("n1", [{"key": "city"}])],
            edges=[],
        )
        fields = extract_input_fields_from_workflow(wf)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].key, "city")

    def test_non_root_text_input_excluded(self) -> None:
        # n1 → n2; n2 has a target so it is not a root node
        wf = _workflow(
            nodes=[
                self._make_text_input_node("n1"),
                self._make_text_input_node("n2"),
            ],
            edges=[{"source": "n1", "target": "n2"}],
        )
        fields = extract_input_fields_from_workflow(wf)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].key, "text")

    def test_inactive_node_excluded(self) -> None:
        wf = _workflow(
            nodes=[self._make_text_input_node("n1", active=False)],
            edges=[],
        )
        self.assertEqual(extract_input_fields_from_workflow(wf), [])

    def test_non_text_input_node_excluded(self) -> None:
        wf = _workflow(
            nodes=[{"id": "n1", "type": "llm", "data": {"active": True}}],
            edges=[],
        )
        self.assertEqual(extract_input_fields_from_workflow(wf), [])

    def test_multiple_input_fields_on_single_node(self) -> None:
        wf = _workflow(
            nodes=[self._make_text_input_node("n1", [{"key": "name"}, {"key": "age"}])],
            edges=[],
        )
        fields = extract_input_fields_from_workflow(wf)
        self.assertEqual([f.key for f in fields], ["name", "age"])


class GetNodeOutputExpressionTests(unittest.TestCase):
    def _node(self, node_type: str, data: dict | None = None) -> dict:
        return {"type": node_type, "data": {"label": "MyNode", **(data or {})}}

    def test_output_node(self) -> None:
        node = self._node("output", {"message": "hello"})
        self.assertEqual(get_node_output_expression(node), "hello")

    def test_llm_text_output(self) -> None:
        node = self._node("llm", {"outputType": "text"})
        self.assertEqual(get_node_output_expression(node), "$MyNode.text")

    def test_llm_image_output(self) -> None:
        node = self._node("llm", {"outputType": "image"})
        self.assertEqual(get_node_output_expression(node), "$MyNode.image")

    def test_http_node(self) -> None:
        node = self._node("http")
        self.assertEqual(get_node_output_expression(node), "$MyNode.body")

    def test_variable_node(self) -> None:
        node = self._node("variable")
        self.assertEqual(get_node_output_expression(node), "$MyNode.value")

    def test_set_node_single_key(self) -> None:
        node = self._node("set", {"mappings": [{"key": "result"}]})
        self.assertEqual(get_node_output_expression(node), "$MyNode.result")

    def test_set_node_multiple_keys(self) -> None:
        node = self._node("set", {"mappings": [{"key": "a"}, {"key": "b"}]})
        self.assertEqual(get_node_output_expression(node), "$MyNode.{a, b}")

    def test_condition_node(self) -> None:
        node = self._node("condition")
        self.assertIn("true/false", get_node_output_expression(node))

    def test_loop_node(self) -> None:
        node = self._node("loop")
        self.assertIn("results", get_node_output_expression(node))

    def test_unknown_node_returns_none(self) -> None:
        node = self._node("unknown_type")
        self.assertIsNone(get_node_output_expression(node))


class ExtractOutputNodeTests(unittest.TestCase):
    def test_returns_none_for_empty_workflow(self) -> None:
        wf = _workflow()
        self.assertIsNone(extract_output_node_from_workflow(wf))

    def test_explicit_output_node_preferred(self) -> None:
        wf = _workflow(
            nodes=[
                {"id": "n1", "type": "llm", "data": {"label": "LLM", "active": True}},
                {
                    "id": "n2",
                    "type": "output",
                    "data": {"label": "Out", "message": "hi", "active": True},
                },
            ],
            edges=[{"source": "n1", "target": "n2"}],
        )
        result = extract_output_node_from_workflow(wf)
        self.assertIsNotNone(result)
        self.assertEqual(result.node_type, "output")

    def test_last_node_used_when_no_output_type(self) -> None:
        wf = _workflow(
            nodes=[
                {"id": "n1", "type": "llm", "data": {"label": "LLM", "active": True}},
                {"id": "n2", "type": "http", "data": {"label": "HTTP", "active": True}},
            ],
            edges=[{"source": "n1", "target": "n2"}],
        )
        result = extract_output_node_from_workflow(wf)
        self.assertIsNotNone(result)
        # n2 has no outgoing edge → it is the end node
        self.assertEqual(result.node_type, "http")


class GetFirstNodeTypeTests(unittest.TestCase):
    def test_returns_none_for_empty_workflow(self) -> None:
        wf = _workflow()
        self.assertIsNone(get_first_node_type(wf))

    def test_returns_type_of_root_node(self) -> None:
        wf = _workflow(
            nodes=[
                {"id": "n1", "type": "textInput", "data": {"active": True}},
                {"id": "n2", "type": "llm", "data": {"active": True}},
            ],
            edges=[{"source": "n1", "target": "n2"}],
        )
        self.assertEqual(get_first_node_type(wf), "textInput")

    def test_skips_sticky_and_error_handler(self) -> None:
        wf = _workflow(
            nodes=[
                {"id": "n0", "type": "sticky", "data": {"active": True}},
                {"id": "n1", "type": "llm", "data": {"active": True}},
            ],
            edges=[],
        )
        self.assertEqual(get_first_node_type(wf), "llm")


class TestJsonEscapeUnescape(unittest.TestCase):
    def test_escape_string_basic(self) -> None:
        """Test basic string escape functionality."""
        result = _safe_json_parse('"Hello World"')
        self.assertEqual(result, "Hello World")

    def test_escape_string_with_quotes(self) -> None:
        """Test escaping string containing quotes."""
        result = _safe_json_parse('"He said \\"Hello\\""')
        self.assertEqual(result, 'He said "Hello"')

    def test_escape_string_with_newlines(self) -> None:
        """Test escaping string with newline characters."""
        result = _safe_json_parse('"Line 1\\nLine 2"')
        self.assertEqual(result, "Line 1\nLine 2")

    def test_escape_string_with_special_chars(self) -> None:
        """Test escaping special characters."""
        result = _safe_json_parse('"Tab\\there\\\\backslash"')
        self.assertEqual(result, "Tab\there\\backslash")

    def test_unescape_string(self) -> None:
        """Test unescaping JSON strings back to original."""

        original = 'Hello\\n\\"World\\"'
        result = _safe_json_parse(f'"{original}"')
        self.assertEqual(result, 'Hello\n"World"')

    def test_unescape_error_handling(self) -> None:
        """Test error handling for invalid JSON strings."""

        invalid_json = '"unclosed'
        self.assertEqual(_safe_json_parse(invalid_json), invalid_json)

    def test_escape_preserves_unicode(self) -> None:
        """Test that escape preserves unicode characters."""
        unicode_str = '"Hello 世界"'
        result = _safe_json_parse(unicode_str)
        self.assertEqual(result, "Hello 世界")

    def test_empty_string_escape(self) -> None:
        """Test escaping empty string."""
        result = _safe_json_parse('""')
        self.assertEqual(result, "")

    def test_escape_whitespace(self) -> None:
        """Test escaping strings with various whitespace."""
        result = _safe_json_parse('"  spaces\\tand\\ttabs  "')
        self.assertEqual(result, "  spaces\tand\ttabs  ")

    def test_non_string_number_input(self) -> None:
        """Test that non-string values are handled gracefully."""
        result = _safe_json_parse(123)
        self.assertEqual(result, 123)

    def test_non_string_undefined_input(self) -> None:
        """Test that None values are handled gracefully."""
        result = _safe_json_parse(None)
        self.assertIsNone(result)

    def test_non_string_dict_input(self) -> None:
        """Test that dict values are handled gracefully."""
        test_dict = {"key": "value"}
        result = _safe_json_parse(test_dict)
        self.assertEqual(result, test_dict)
