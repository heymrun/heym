from __future__ import annotations

import json

from app.services.code_python_executor import execute_code
from app.services.node_execution.base import NodeExecutionContext


def _resolve_value(ctx: NodeExecutionContext, value: object) -> object:
    """Resolve expressions inside an already-parsed Parameters value."""
    if isinstance(value, dict):
        return {key: _resolve_value(ctx, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value(ctx, item) for item in value]
    if not isinstance(value, str) or "$" not in value:
        return value
    # A value that is exactly one expression keeps its resolved type, so a list
    # stays a list and a number stays a number instead of being stringified.
    if value.startswith("$") and " " not in value:
        return ctx.executor.resolve_expression(value, ctx.inputs, ctx.node_id, preserve_type=True)
    return ctx.executor.evaluate_message_template(value, ctx.inputs, ctx.node_id)


def _resolve_parameters(ctx: NodeExecutionContext) -> dict:
    """Resolve the Parameters JSON field, expanding any ``$`` expressions.

    Parsed first, resolved second. Substituting into the raw text instead would
    break the JSON as soon as a resolved string contained a quote or a newline.
    """
    template = ctx.node_data.get("codeParameters", "")
    if not isinstance(template, str) or not template.strip():
        return {}

    try:
        parsed = json.loads(template)
    except json.JSONDecodeError:
        # Not JSON on its own: fall back to substituting first, which supports
        # unquoted expressions such as {"rows": $fetch.result}.
        rendered = ctx.executor.evaluate_message_template(template, ctx.inputs, ctx.node_id)
        if isinstance(rendered, dict):
            return rendered
        try:
            parsed = json.loads(rendered if isinstance(rendered, str) else str(rendered))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(
                f"Parameters must be valid JSON after expression resolution: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError('Parameters must be a JSON object, for example {"name": "Ada"}.')
        return parsed

    if not isinstance(parsed, dict):
        raise ValueError('Parameters must be a JSON object, for example {"name": "Ada"}.')
    resolved = _resolve_value(ctx, parsed)
    if not isinstance(resolved, dict):
        raise ValueError('Parameters must be a JSON object, for example {"name": "Ada"}.')
    return resolved


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the code node."""
    code = str(ctx.node_data.get("codeSource") or "")
    if not code.strip():
        raise ValueError("Code is empty. Define a main(params) function to run.")

    requirements = str(ctx.node_data.get("codeRequirements") or "")
    allow_network = bool(ctx.node_data.get("codeAllowNetwork", False))
    params = _resolve_parameters(ctx)

    outcome = execute_code(
        code=code,
        requirements=requirements,
        params=params,
        allow_network=allow_network,
    )
    return {
        "result": outcome.result,
        "logs": outcome.logs,
        "install": {
            "ok": outcome.install_ok,
            "tool": outcome.install_tool,
            "log": outcome.install_log,
        },
    }
