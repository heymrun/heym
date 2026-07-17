"""Runtime validation for node output data contracts."""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker, SchemaError, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

MAX_SCHEMA_BYTES = 128 * 1024
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 4096
MAX_SCHEMA_PATTERN_LENGTH = 2048
MAX_VALIDATION_ERRORS = 20
_FORMAT_CHECKER = FormatChecker()
_LOCAL_SCHEMA_URI = "urn:heym:submitted-schema"
_REF_KEYWORDS = frozenset({"$ref", "$dynamicRef", "$recursiveRef"})
_ENVELOPE_KEYS = frozenset({"name", "schema", "strict", "description"})
_VOCABULARY_FILENAME = "json_schema_vocabulary.json"
_VOCABULARY_PATH = Path(__file__).resolve().parent / _VOCABULARY_FILENAME


def _load_schema_vocabulary() -> dict[str, frozenset[str]]:
    """Load the package-local Draft 2020-12 vocabulary synced from shared/."""
    if not _VOCABULARY_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {_VOCABULARY_PATH}; run sh scripts/sync-json-schema-vocabulary.sh"
        )
    with _VOCABULARY_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return {
        "formats": frozenset(payload["formats"]),
        "keywords": frozenset(payload["keywords"]),
        "mapKeywords": frozenset(payload["mapKeywords"]),
        "childKeywords": frozenset(payload["childKeywords"]),
        "listKeywords": frozenset(payload["listKeywords"]),
    }


_SCHEMA_VOCABULARY = _load_schema_vocabulary()
_SUPPORTED_SCHEMA_KEYWORDS = _SCHEMA_VOCABULARY["keywords"]
_SCHEMA_MAP_KEYWORDS = _SCHEMA_VOCABULARY["mapKeywords"]
_SCHEMA_CHILD_KEYWORDS = _SCHEMA_VOCABULARY["childKeywords"]
_SCHEMA_LIST_KEYWORDS = _SCHEMA_VOCABULARY["listKeywords"]
_SUPPORTED_FORMATS = _SCHEMA_VOCABULARY["formats"]


@dataclass(frozen=True)
class ProviderSchemaCapabilities:
    """Provider-specific structured-output constraints."""

    root_object_required: bool = True
    all_properties_required: bool = True
    additional_properties_forbidden: bool = True


STRICT_PROVIDER_SCHEMA_CAPABILITIES = ProviderSchemaCapabilities()
_PROVIDER_SCHEMA_CAPABILITIES = {
    "openai": STRICT_PROVIDER_SCHEMA_CAPABILITIES,
    "google": STRICT_PROVIDER_SCHEMA_CAPABILITIES,
    "custom": STRICT_PROVIDER_SCHEMA_CAPABILITIES,
}


def get_provider_schema_capabilities(provider: str | None) -> ProviderSchemaCapabilities:
    """Return structured-output constraints for a provider family."""
    return _PROVIDER_SCHEMA_CAPABILITIES.get(
        (provider or "").strip().lower(),
        STRICT_PROVIDER_SCHEMA_CAPABILITIES,
    )


def _register_format_checkers() -> None:
    """Register validators for formats not covered by jsonschema's defaults."""

    @_FORMAT_CHECKER.checks("date-time")
    def is_date_time(value: object) -> bool:
        if not isinstance(value, str):
            return True
        if len(value) < 11 or value[10] != "T":
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    @_FORMAT_CHECKER.checks("date")
    def is_date(value: object) -> bool:
        if not isinstance(value, str):
            return True
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    @_FORMAT_CHECKER.checks("time")
    def is_time(value: object) -> bool:
        if not isinstance(value, str):
            return True
        try:
            time.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    @_FORMAT_CHECKER.checks("duration")
    def is_duration(value: object) -> bool:
        return not isinstance(value, str) or bool(
            re.fullmatch(
                r"P(?=\d|T\d)(?:\d+Y)?(?:\d+M)?(?:\d+D)?"
                r"(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?",
                value,
            )
        )

    @_FORMAT_CHECKER.checks("uri-reference")
    def is_uri_reference(value: object) -> bool:
        return not isinstance(value, str) or not any(
            ord(char) < 0x20 or char.isspace() for char in value
        )

    @_FORMAT_CHECKER.checks("uri")
    def is_uri(value: object) -> bool:
        if not is_uri_reference(value):
            return False
        if not isinstance(value, str):
            return True
        try:
            return bool(urlsplit(value).scheme)
        except ValueError:
            return False

    @_FORMAT_CHECKER.checks("url")
    def is_url(value: object) -> bool:
        if not is_uri(value):
            return False
        if not isinstance(value, str):
            return True
        try:
            return urlsplit(value).scheme in {"http", "https"}
        except ValueError:
            return False

    @_FORMAT_CHECKER.checks("uri-template")
    def is_uri_template(value: object) -> bool:
        if not isinstance(value, str):
            return True
        return value.count("{") == value.count("}") and not any(
            ord(char) < 0x20 or char.isspace() for char in value
        )

    @_FORMAT_CHECKER.checks("hostname")
    def is_hostname(value: object) -> bool:
        if not isinstance(value, str) or len(value) > 253:
            return not isinstance(value, str)
        return bool(
            re.fullmatch(
                r"(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?",
                value,
            )
        )

    @_FORMAT_CHECKER.checks("json-pointer")
    def is_json_pointer(value: object) -> bool:
        return (
            not isinstance(value, str)
            or value == ""
            or bool(re.fullmatch(r"(?:/(?:[^~/]|~[01])*)*", value))
        )

    @_FORMAT_CHECKER.checks("relative-json-pointer")
    def is_relative_json_pointer(value: object) -> bool:
        return not isinstance(value, str) or bool(
            re.fullmatch(r"(?:0|[1-9]\d*)(?:#|(?:/(?:[^~/]|~[01])*)*)", value)
        )

    @_FORMAT_CHECKER.checks("regex")
    def is_regex(value: object) -> bool:
        if not isinstance(value, str):
            return True
        try:
            re.compile(value)
        except re.error:
            return False
        return True

    @_FORMAT_CHECKER.checks("ipv4")
    def is_ipv4(value: object) -> bool:
        if not isinstance(value, str):
            return True
        try:
            return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
        except ValueError:
            return False

    @_FORMAT_CHECKER.checks("ipv6")
    def is_ipv6(value: object) -> bool:
        if not isinstance(value, str):
            return True
        try:
            return isinstance(ipaddress.ip_address(value), ipaddress.IPv6Address)
        except ValueError:
            return False

    @_FORMAT_CHECKER.checks("uuid")
    def is_uuid(value: object) -> bool:
        if not isinstance(value, str):
            return True
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True


_register_format_checkers()


@dataclass(frozen=True)
class DataContractViolationError(Exception):
    """Raised when a node output does not satisfy its configured contract."""

    node_label: str
    errors: tuple[str, ...]
    trace_id: str | None = None

    def __str__(self) -> str:
        detail = self.errors[0] if self.errors else "unknown validation error"
        return f"Output contract failed for {self.node_label}: {detail}"

    def __reduce__(self) -> tuple[object, tuple[str, tuple[str, ...], str | None]]:
        """Return constructor arguments that preserve the dataclass fields when pickled."""
        return type(self), (self.node_label, self.errors, self.trace_id)


def parse_json_schema(
    value: Any,
    *,
    field_name: str = "JSON Schema",
    allow_envelope: bool = False,
) -> dict[str, Any] | None:
    """Parse and structurally validate a user-provided JSON Schema definition."""
    if value in (None, ""):
        return None
    schema: Any = value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise SchemaError(f"{field_name} exceeds the {MAX_SCHEMA_BYTES} byte limit")
        try:
            schema = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{field_name} is not valid JSON: {exc.msg}") from exc
    if not isinstance(schema, dict):
        raise SchemaError(f"{field_name} must be a JSON object")
    try:
        serialized_size = len(json.dumps(schema, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field_name} must contain JSON-compatible values") from exc
    if serialized_size > MAX_SCHEMA_BYTES:
        raise SchemaError(f"{field_name} exceeds the {MAX_SCHEMA_BYTES} byte limit")
    has_envelope_shape = "schema" in schema and set(schema).issubset(_ENVELOPE_KEYS)
    if has_envelope_shape:
        if not allow_envelope:
            raise SchemaError(f"{field_name} envelope is not supported")
        if not isinstance(schema["schema"], dict):
            raise SchemaError(f"{field_name} envelope 'schema' must be a JSON object")
        schema = schema["schema"]
    _check_schema_safety(schema, field_name=field_name)
    return schema


def parse_data_contract(value: Any) -> dict[str, Any] | None:
    """Parse a node's output contract into a JSON Schema object."""
    return parse_json_schema(value, field_name="Output contract", allow_envelope=True)


def validate_json_schema(
    value: Any,
    *,
    field_name: str = "JSON Schema",
    allow_envelope: bool = False,
) -> dict[str, Any] | None:
    """Parse and validate a JSON Schema definition without validating an instance."""
    schema = parse_json_schema(value, field_name=field_name, allow_envelope=allow_envelope)
    if schema is not None:
        _validate_parsed_schema(schema, field_name=field_name)
    return schema


def _validate_parsed_schema(schema: dict[str, Any], *, field_name: str) -> None:
    """Validate a schema that has already passed parsing and safety checks."""
    Draft202012Validator.check_schema(schema)
    _build_validator(schema, field_name=field_name)


def validate_provider_json_schema(
    value: Any,
    *,
    field_name: str = "JSON output schema",
    provider: str | None = None,
    capabilities: ProviderSchemaCapabilities | None = None,
) -> dict[str, Any] | None:
    """Validate the stricter schema subset accepted by provider JSON output mode."""
    schema = validate_json_schema(value, field_name=field_name)
    if schema is None:
        return None
    resolved_capabilities = capabilities or get_provider_schema_capabilities(provider)
    if resolved_capabilities.root_object_required and schema.get("type") != "object":
        raise SchemaError(f"{field_name} root must be an object for strict output")
    _validate_provider_schema_nodes(
        schema,
        path="root",
        field_name=field_name,
        capabilities=resolved_capabilities,
    )
    return schema


def _validate_provider_schema_nodes(
    schema: Any,
    *,
    path: str,
    field_name: str,
    capabilities: ProviderSchemaCapabilities,
) -> None:
    """Check strict provider constraints on every object schema in a tree."""
    if isinstance(schema, list):
        for index, child in enumerate(schema):
            _validate_provider_schema_nodes(
                child,
                path=f"{path}[{index}]",
                field_name=field_name,
                capabilities=capabilities,
            )
        return
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object" or isinstance(schema.get("properties"), dict):
        properties = schema.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise SchemaError(f"{field_name} properties at {path} must be an object")
        additional_properties = schema.get("additionalProperties")
        if capabilities.additional_properties_forbidden and additional_properties not in (
            None,
            False,
        ):
            raise SchemaError(
                f"{field_name} additionalProperties at {path} must be false or omitted"
            )
        property_names = set(properties or {})
        required = schema.get("required", [])
        if capabilities.all_properties_required and (
            not isinstance(required, list)
            or len(required) != len(set(required))
            or set(required) != property_names
        ):
            raise SchemaError(f"{field_name} at {path} must list every property in required")
    for key, child in schema.items():
        _validate_provider_schema_nodes(
            child,
            path=f"{path}.{key}",
            field_name=field_name,
            capabilities=capabilities,
        )


def validate_node_output(output: Any, contract: Any, node_label: str) -> None:
    """Validate a node output, raising a contract or schema error when needed."""
    schema = parse_data_contract(contract)
    if schema is None:
        return
    _validate_parsed_schema(schema, field_name="Output contract")
    _validate_instance(output, schema, node_label)


def validate_json_output(output: Any, schema_value: Any, node_label: str) -> None:
    """Validate structured JSON output against a raw JSON Schema definition."""
    schema = validate_json_schema(
        schema_value,
        field_name="JSON output schema",
        allow_envelope=False,
    )
    if schema is not None:
        _validate_instance(output, schema, node_label)


def _validate_instance(output: Any, schema: dict[str, Any], node_label: str) -> None:
    """Validate one JSON-compatible value against a previously parsed schema."""
    validator = _build_validator(schema, field_name="Output contract")
    errors = tuple(
        _format_validation_error(error)
        for index, error in enumerate(validator.iter_errors(output))
        if index < MAX_VALIDATION_ERRORS
    )
    if errors:
        raise DataContractViolationError(node_label=node_label, errors=errors)


def _format_validation_error(error: ValidationError) -> str:
    """Format a JSON Schema error as a concise, user-facing message."""
    path = ".".join(str(part) for part in error.absolute_path)
    location = f" at '{path}'" if path else ""
    return f"{error.message}{location}"


def is_valid_json_instance(output: Any, schema: dict[str, Any]) -> bool:
    """Return whether a JSON value satisfies a previously validated schema."""
    return _build_validator(schema, field_name="JSON Schema").is_valid(output)


def _build_validator(schema: dict[str, Any], *, field_name: str) -> Draft202012Validator:
    """Build a validator rooted at the submitted schema and resolve local references."""
    serialized_schema = json.dumps(
        schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    try:
        return _build_cached_validator(serialized_schema)
    except Unresolvable as exc:
        reference = getattr(exc, "ref", None) or str(exc)
        if reference.startswith("/"):
            reference = f"#{reference}"
        raise SchemaError(f"{field_name} contains unresolved reference '{reference}'") from exc


@lru_cache(maxsize=128)
def _build_cached_validator(serialized_schema: str) -> Draft202012Validator:
    """Build and cache a validator for an immutable canonical schema string."""
    schema = json.loads(serialized_schema)
    registry = Registry().with_resource(
        _LOCAL_SCHEMA_URI,
        Resource.from_contents(schema, default_specification=DRAFT202012),
    )
    validator = Draft202012Validator(
        schema,
        format_checker=_FORMAT_CHECKER,
        registry=registry,
    )
    _resolve_references(registry.resolver(_LOCAL_SCHEMA_URI), schema)
    return validator


def _resolve_references(resolver: Any, schema: Any) -> None:
    """Resolve every local reference in a schema, including unused definitions."""
    if isinstance(schema, dict):
        current_resolver = (
            resolver.in_subresource(
                Resource.from_contents(schema, default_specification=DRAFT202012)
            )
            if "$id" in schema
            else resolver
        )
        for keyword in _REF_KEYWORDS.intersection(schema):
            current_resolver.lookup(schema[keyword])
        for child in schema.values():
            _resolve_references(current_resolver, child)
    elif isinstance(schema, list):
        for child in schema:
            _resolve_references(resolver, child)


def validate_workflow_node_schemas(nodes: Any) -> None:
    """Validate schema-bearing node fields before a workflow is persisted."""
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data")
        if not isinstance(node_data, dict):
            continue
        label = str(node_data.get("label") or node.get("id") or "node")
        if node_data.get("outputContract") not in (None, ""):
            validate_json_schema(
                node_data["outputContract"],
                field_name=f"Output contract for '{label}'",
                allow_envelope=True,
            )
        if node_data.get("jsonOutputSchema") not in (None, ""):
            schema_field_name = f"JSON output schema for '{label}'"
            if node_data.get("jsonOutputEnabled"):
                validate_provider_json_schema(
                    node_data["jsonOutputSchema"],
                    field_name=schema_field_name,
                )
            else:
                validate_json_schema(
                    node_data["jsonOutputSchema"],
                    field_name=schema_field_name,
                )


def _check_schema_safety(schema: dict[str, Any], *, field_name: str) -> None:
    """Reject dangerous or excessively deep schema constructs before validation."""
    _check_schema_keywords(schema, field_name=field_name, path="root")
    stack: list[tuple[Any, int]] = [(schema, 0)]
    visited_nodes = 0
    while stack:
        value, depth = stack.pop()
        visited_nodes += 1
        if visited_nodes > MAX_SCHEMA_NODES:
            raise SchemaError(f"{field_name} exceeds the maximum schema node count")
        if depth > MAX_SCHEMA_DEPTH:
            raise SchemaError(f"{field_name} exceeds the maximum nesting depth")
        if isinstance(value, dict):
            pattern = value.get("pattern")
            if isinstance(pattern, str) and len(pattern) > MAX_SCHEMA_PATTERN_LENGTH:
                raise SchemaError(f"{field_name} pattern length exceeds the maximum pattern length")
            pattern_properties = value.get("patternProperties")
            if isinstance(pattern_properties, dict):
                for pattern in pattern_properties:
                    if len(pattern) > MAX_SCHEMA_PATTERN_LENGTH:
                        raise SchemaError(
                            f"{field_name} patternProperties key length exceeds the maximum pattern length"
                        )
            format_name = value.get("format")
            if format_name is not None and (
                not isinstance(format_name, str) or format_name not in _SUPPORTED_FORMATS
            ):
                raise SchemaError(f"{field_name} contains unsupported format '{format_name}'")
            for keyword in _REF_KEYWORDS.intersection(value):
                ref = value[keyword]
                if not isinstance(ref, str):
                    raise SchemaError(f"{field_name} {keyword} must be a string")
                parsed = urlsplit(ref)
                if not ref.startswith("#") or parsed.scheme or parsed.netloc:
                    raise SchemaError(f"{field_name} may only use local {keyword} values")
            schema_id = value.get("$id")
            if schema_id is not None:
                if not isinstance(schema_id, str):
                    raise SchemaError(f"{field_name} $id must be a string")
                parsed_id = urlsplit(schema_id)
                if (parsed_id.scheme and parsed_id.scheme != "urn") or parsed_id.netloc:
                    raise SchemaError(f"{field_name} may only use local $id values")
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)


def _check_schema_keywords(schema: Any, *, field_name: str, path: str) -> None:
    """Reject keywords outside the supported Draft 2020-12 vocabulary."""
    if isinstance(schema, list):
        for index, child in enumerate(schema):
            _check_schema_keywords(child, field_name=field_name, path=f"{path}[{index}]")
        return
    if not isinstance(schema, dict):
        return

    for keyword, value in schema.items():
        if keyword not in _SUPPORTED_SCHEMA_KEYWORDS:
            raise SchemaError(f"{field_name} contains unsupported keyword '{keyword}' at {path}")
        if keyword in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for name, child in value.items():
                _check_schema_keywords(
                    child,
                    field_name=field_name,
                    path=f"{path}.{keyword}.{name}",
                )
        elif keyword in _SCHEMA_CHILD_KEYWORDS:
            _check_schema_keywords(value, field_name=field_name, path=f"{path}.{keyword}")
        elif keyword in _SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            for index, child in enumerate(value):
                _check_schema_keywords(
                    child,
                    field_name=field_name,
                    path=f"{path}.{keyword}[{index}]",
                )
