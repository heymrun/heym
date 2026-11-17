"""JSON node fields that carry ``$`` expressions: parsed first, resolved second.

Substituting resolved values into the raw JSON text breaks the JSON as soon as a value
holds a double quote or a line break, which text from chat, email, forms and LLMs does
all the time. When the field is valid JSON on its own, it is parsed first and each key and
string value is resolved in place. A key that is only ``$`` plus a name, such as the data
table operators ``$gt`` and ``$in``, is kept as written. A template that is not JSON yet, such as
``{"age": $start.age}`` with an unquoted expression, is still substituted first, exactly
as before. The Code node's Parameters, the Google Sheets values and the RAG node's
metadata follow the same rule.

Parsing also decodes JSON escapes, so ``\\n`` inside an expression's quoted argument, as in
``"$input.notes.replace('\\n', ' ')"``, becomes a real line break the expression cannot
parse. A value with ``$`` and a line break that comes back unresolved therefore sends the
whole field back to substitution, which is what it did before.
"""

from __future__ import annotations

import json
import re

_OPERATOR_KEY = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


class _UnresolvedLineBreakError(Exception):
    """A value whose expression did not resolve after parsing decoded a line break into it."""


def _resolve_string(executor, value: str, inputs: dict, node_id: str) -> str:
    if "$" not in value:
        return value
    resolved = executor.evaluate_message_template(value, inputs, node_id)
    if resolved == value and ("\n" in value or "\r" in value):
        raise _UnresolvedLineBreakError
    return resolved


def _resolve_key(executor, key: str, inputs: dict, node_id: str) -> str:
    # A key that is only `$` plus a name is an operator such as `$gt` or `$in` in a data
    # table filter. Resolving it would turn it into the output of a node labelled `gt`.
    if _OPERATOR_KEY.fullmatch(key):
        return key
    return _resolve_string(executor, key, inputs, node_id)


def resolve_json_values(executor, value: object, inputs: dict, node_id: str) -> object:
    """Resolve ``$`` expressions in every key and string value of already-parsed JSON.

    A key that is only ``$`` plus a name, such as ``$gt``, is kept as written; a key with a
    path, such as ``$start.body.kind``, resolves.
    """
    if isinstance(value, dict):
        return {
            _resolve_key(executor, key, inputs, node_id): resolve_json_values(
                executor, item, inputs, node_id
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_json_values(executor, item, inputs, node_id) for item in value]
    if isinstance(value, str):
        return _resolve_string(executor, value, inputs, node_id)
    return value


def resolve_json_field(executor, template: object, inputs: dict, node_id: str) -> object:
    """The field's parsed value with its expressions resolved. Raises JSONDecodeError if invalid."""
    if isinstance(template, str):
        try:
            parsed = json.loads(template)
        except json.JSONDecodeError:
            pass
        else:
            try:
                return resolve_json_values(executor, parsed, inputs, node_id)
            except _UnresolvedLineBreakError:
                pass
    rendered = executor.evaluate_message_template(template, inputs, node_id)
    return json.loads(rendered) if isinstance(rendered, str) else rendered


def render_json_template(executor, template: str, inputs: dict, node_id: str) -> str:
    """The field as JSON text with its expressions resolved, for callers that parse text.

    Valid JSON is resolved per value and serialized again, so a quote or a line break in
    a value stays inside it. Anything else is substituted as before.
    """
    try:
        parsed = json.loads(template)
        resolved = resolve_json_values(executor, parsed, inputs, node_id)
    except (json.JSONDecodeError, TypeError, _UnresolvedLineBreakError):
        return executor.evaluate_message_template(template, inputs, node_id)
    return json.dumps(resolved, ensure_ascii=False)
