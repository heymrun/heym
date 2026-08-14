from __future__ import annotations

import json

from app.services.code_python_executor import execute_code
from app.services.node_execution.base import NodeExecutionContext


def _resolve_parameters(ctx: NodeExecutionContext) -> dict:
    """Resolve the Parameters JSON field, expanding any ``$`` expressions."""
    template = ctx.node_data.get("codeParameters", "")
    if not isinstance(template, str) or not template.strip():
        return {}
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
