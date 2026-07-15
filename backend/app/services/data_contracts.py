"""Runtime validation for node output data contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError


@dataclass(frozen=True)
class DataContractViolationError(Exception):
    """Raised when a node output does not satisfy its configured contract."""

    node_label: str
    errors: tuple[str, ...]

    def __str__(self) -> str:
        return f"Output contract failed for {self.node_label}: {self.errors[0]}"


def parse_data_contract(value: Any) -> dict[str, Any] | None:
    """Parse a node's output contract into a JSON Schema object."""
    if value in (None, ""):
        return None
    schema: Any = value
    if isinstance(value, str):
        try:
            schema = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"Output contract is not valid JSON: {exc.msg}") from exc
    if not isinstance(schema, dict):
        raise SchemaError("Output contract must be a JSON object")
    if isinstance(schema.get("schema"), dict):
        schema = schema["schema"]
    return schema


def validate_node_output(output: Any, contract: Any, node_label: str) -> None:
    """Validate a node output, raising a contract or schema error when needed."""
    schema = parse_data_contract(contract)
    if schema is None:
        return
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = tuple(_format_validation_error(error) for error in validator.iter_errors(output))
    if errors:
        raise DataContractViolationError(node_label=node_label, errors=errors)


def _format_validation_error(error: ValidationError) -> str:
    """Format a JSON Schema error as a concise, user-facing message."""
    path = ".".join(str(part) for part in error.absolute_path)
    location = f" at '{path}'" if path else ""
    return f"{error.message}{location}"
