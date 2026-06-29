from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the textInput node."""
    node_data = ctx.node_data

    initial_inputs = node_data.get("_initial_inputs", {})
    if initial_inputs:
        output = dict(initial_inputs)
        body = output.get("body")
        if isinstance(body, dict):
            output.update(body)
    else:
        default_value = node_data.get("value", "")
        if default_value:
            output = {"text": default_value}
        else:
            output = {}
    return output
