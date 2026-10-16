"""Check a model's reply against the JSON output a node asked for, and word the retry."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

MAX_OUTPUT_REPAIRS = 2
_ERROR_MAX = 300
_ERRORS_LISTED = 3
_FENCED_JSON = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class OutputCheck:
    """`text` is the reply to use when `ok`, with any wrapping code fence removed."""

    ok: bool
    text: str
    error: str | None = None


def unwrap_json_fence(text: str) -> str:
    """Models wrap JSON in a code fence; a reply with several fenced blocks stays untouched."""
    match = _FENCED_JSON.match(text.strip())
    if match is None or "```" in match.group(1):
        return text
    return match.group(1)


def echoes_schema(parsed: Any, schema: dict[str, Any]) -> bool:
    """True when the reply is the JSON Schema itself instead of an object that follows it."""
    declared = schema.get("properties") or {}
    return (
        isinstance(parsed, dict)
        and parsed.get("type") == "object"
        and isinstance(parsed.get("properties"), dict)
        and "properties" not in declared
    )


def _short(message: str) -> str:
    collapsed = " ".join(message.split())
    return collapsed if len(collapsed) <= _ERROR_MAX else collapsed[: _ERROR_MAX - 3] + "..."


def _schema_of(response_format: dict[str, Any]) -> dict[str, Any] | None:
    if response_format.get("type") != "json_schema":
        return None
    schema = (response_format.get("json_schema") or {}).get("schema")
    return schema if isinstance(schema, dict) else None


def _schema_error(parsed: Any, schema: dict[str, Any]) -> str | None:
    if echoes_schema(parsed, schema):
        return "the reply is the JSON schema itself, not an object that follows it"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return None
    # Extra fields do no harm, so only a reply the node cannot use is worth another try.
    errors = [
        error
        for error in Draft202012Validator(schema).iter_errors(parsed)
        if error.validator != "additionalProperties"
    ]
    if not errors:
        return None
    errors.sort(key=lambda error: len(error.absolute_path))
    problems = []
    for error in errors[:_ERRORS_LISTED]:
        where = ".".join(str(part) for part in error.absolute_path)
        problems.append(f"{where}: {error.message}" if where else error.message)
    return _short("; ".join(problems))


def check_json_output(text: str, response_format: dict[str, Any]) -> OutputCheck:
    """Decide whether `text` is the JSON `response_format` asked for."""
    candidate = unwrap_json_fence(text.strip()).strip()
    if not candidate:
        return OutputCheck(False, text, "the reply was empty")
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return OutputCheck(
            False, text, f"the reply is not valid JSON ({exc.msg} at line {exc.lineno})"
        )
    if isinstance(parsed, str) and parsed.strip().startswith(("{", "[")):
        # A JSON string holding JSON: the node unwraps it the same way.
        try:
            candidate = parsed.strip()
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return OutputCheck(False, text, "the reply is a JSON string, not a JSON object")
    schema = _schema_of(response_format)
    error = _schema_error(parsed, schema) if schema is not None else None
    if error is not None:
        return OutputCheck(False, text, error)
    return OutputCheck(True, candidate)


JSON_ONLY = (
    "Respond with a single valid JSON object only. Do not use markdown code fences and do not "
    "add any text before or after it."
)


def json_instruction(response_format: dict[str, Any] | None) -> str | None:
    """For APIs with no JSON mode field, the contract travels in the system prompt."""
    if not response_format:
        return None
    format_type = response_format.get("type")
    if format_type == "json_object":
        return JSON_ONLY
    if format_type == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema") or {}
        return (
            f"{JSON_ONLY} It must conform to this JSON Schema, and you must output the object "
            f"itself, never the schema:\n{json.dumps(schema)}"
        )
    return None


def repair_instruction(error: str | None) -> str:
    """The follow-up message that asks the model to fix its reply."""
    return (
        f"Your previous reply could not be used: {_short(error or 'it was not valid JSON')}. "
        "Reply again with only the corrected JSON object. Do not use markdown code fences, do not "
        "add any text before or after the JSON, and do not repeat the schema."
    )
