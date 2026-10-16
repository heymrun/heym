"""Checking a model's JSON reply before a node accepts it."""

import unittest

from app.services.json_output import (
    MAX_OUTPUT_REPAIRS,
    check_json_output,
    repair_instruction,
    unwrap_json_fence,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "email_address": {"type": "string"},
        "consumed": {"type": "boolean"},
        "count": {"type": "integer"},
    },
    "required": ["email_address", "consumed"],
    "additionalProperties": False,
}
RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "output", "schema": SCHEMA}}
OBJECT_FORMAT = {"type": "json_object"}
GOOD = '{"email_address": "a@b.c", "consumed": false}'


class TestParsing(unittest.TestCase):
    def test_plain_json_passes_untouched(self) -> None:
        check = check_json_output(GOOD, RESPONSE_FORMAT)
        self.assertTrue(check.ok)
        self.assertEqual(check.text, GOOD)

    def test_a_wrapping_code_fence_is_removed_not_retried(self) -> None:
        check = check_json_output(f"```json\n{GOOD}\n```", RESPONSE_FORMAT)
        self.assertTrue(check.ok)
        self.assertEqual(check.text, GOOD)

    def test_a_json_string_holding_json_is_accepted_like_the_node_does(self) -> None:
        import json

        check = check_json_output(json.dumps(GOOD), RESPONSE_FORMAT)
        self.assertTrue(check.ok)
        self.assertEqual(check.text, GOOD)

    def test_prose_around_json_is_rejected(self) -> None:
        check = check_json_output(f"Here is the result: {GOOD}", RESPONSE_FORMAT)
        self.assertFalse(check.ok)
        self.assertIn("not valid JSON", check.error or "")

    def test_truncated_json_is_rejected(self) -> None:
        check = check_json_output('{"email_address": "a@b.c", "consu', RESPONSE_FORMAT)
        self.assertFalse(check.ok)

    def test_empty_reply_is_rejected(self) -> None:
        for reply in ("", "   \n"):
            check = check_json_output(reply, RESPONSE_FORMAT)
            self.assertFalse(check.ok)
            self.assertIn("empty", check.error or "")

    def test_two_fenced_blocks_are_rejected(self) -> None:
        reply = f'```json\n{{"type": "object"}}\n```\n\n```json\n{GOOD}\n```'
        self.assertFalse(check_json_output(reply, RESPONSE_FORMAT).ok)


class TestSchema(unittest.TestCase):
    def test_missing_required_field_is_named(self) -> None:
        check = check_json_output('{"email_address": "a@b.c"}', RESPONSE_FORMAT)
        self.assertFalse(check.ok)
        self.assertIn("consumed", check.error or "")

    def test_every_problem_is_listed_so_one_repair_can_fix_them_all(self) -> None:
        check = check_json_output('{"full_name": "Anna", "years": 31}', RESPONSE_FORMAT)
        self.assertFalse(check.ok)
        self.assertIn("email_address", check.error or "")
        self.assertIn("consumed", check.error or "")

    def test_at_most_three_problems_are_listed(self) -> None:
        schema = {
            "type": "object",
            "properties": {name: {"type": "string"} for name in "abcdef"},
            "required": list("abcdef"),
        }
        check = check_json_output("{}", {"type": "json_schema", "json_schema": {"schema": schema}})
        self.assertEqual((check.error or "").count(" is a required property"), 3)

    def test_wrong_type_is_reported_with_its_path(self) -> None:
        check = check_json_output('{"email_address": "a@b.c", "consumed": "no"}', RESPONSE_FORMAT)
        self.assertFalse(check.ok)
        self.assertIn("consumed", check.error or "")

    def test_an_array_where_an_object_is_required_is_rejected(self) -> None:
        self.assertFalse(check_json_output("[1, 2]", RESPONSE_FORMAT).ok)

    def test_extra_fields_are_harmless(self) -> None:
        check = check_json_output(
            '{"email_address": "a@b.c", "consumed": true, "note": "hi"}', RESPONSE_FORMAT
        )
        self.assertTrue(check.ok)

    def test_a_reply_that_is_the_schema_itself_is_rejected(self) -> None:
        import json

        check = check_json_output(json.dumps(SCHEMA), RESPONSE_FORMAT)
        self.assertFalse(check.ok)
        self.assertIn("schema", check.error or "")

    def test_a_schema_that_really_declares_properties_is_not_an_echo(self) -> None:
        schema = {"type": "object", "properties": {"properties": {"type": "object"}}}
        response_format = {"type": "json_schema", "json_schema": {"schema": schema}}
        self.assertTrue(
            check_json_output('{"properties": {"a": 1}, "type": "x"}', response_format).ok
        )

    def test_an_unusable_schema_falls_back_to_parsing_only(self) -> None:
        response_format = {"type": "json_schema", "json_schema": {"schema": {"type": "nonsense"}}}
        self.assertTrue(check_json_output(GOOD, response_format).ok)

    def test_error_text_stays_short(self) -> None:
        reply = '{"email_address": "' + "x" * 5000 + '", "consumed": 3}'
        self.assertLess(len(check_json_output(reply, RESPONSE_FORMAT).error or ""), 400)


class TestJsonObjectMode(unittest.TestCase):
    def test_any_json_value_parses(self) -> None:
        self.assertTrue(check_json_output('{"a": 1}', OBJECT_FORMAT).ok)
        self.assertTrue(check_json_output("[1]", OBJECT_FORMAT).ok)

    def test_invalid_json_is_rejected(self) -> None:
        self.assertFalse(check_json_output("sure!", OBJECT_FORMAT).ok)


class TestHelpers(unittest.TestCase):
    def test_unwrap_leaves_non_fenced_and_multi_block_text_alone(self) -> None:
        self.assertEqual(unwrap_json_fence('{"a": 1}'), '{"a": 1}')
        multi = "```json\n{}\n```\n\n```json\n{}\n```"
        self.assertEqual(unwrap_json_fence(multi), multi)

    def test_repair_instruction_carries_the_error_and_the_rules(self) -> None:
        text = repair_instruction("missing required field(s): consumed")
        self.assertIn("missing required field(s): consumed", text)
        self.assertIn("code fences", text)
        self.assertIn("JSON", text)

    def test_repair_instruction_opens_with_the_sentence_the_trace_view_recognises(self) -> None:
        """frontend/src/lib/traceSteps.ts labels a user turn that starts this way as an auto fix."""
        self.assertTrue(
            repair_instruction("x").startswith("Your previous reply could not be used:")
        )

    def test_the_repair_budget_is_small(self) -> None:
        self.assertEqual(MAX_OUTPUT_REPAIRS, 2)
