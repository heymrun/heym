from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the websocketTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "eventName": trigger_inputs.get("eventName"),
        "url": trigger_inputs.get("url"),
        "triggered_at": trigger_inputs.get("triggered_at"),
        "message": trigger_inputs.get("message"),
        "connection": trigger_inputs.get("connection"),
        "close": trigger_inputs.get("close"),
    }
    return output
