from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the telegramTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "update": trigger_inputs.get("update", {}),
        "message": trigger_inputs.get("message", {}),
        "callback_query": trigger_inputs.get("callback_query", {}),
        "headers": trigger_inputs.get("headers", {}),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
    return output
