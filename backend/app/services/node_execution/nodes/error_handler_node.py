from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the errorHandler node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    error_info = inputs.get("error", {})
    message_template = node_data.get("message", "")
    output = {"error": error_info}
    if message_template:
        output["message"] = self.evaluate_message_template(message_template, inputs, node_id)
    return output
