from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the discordTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "interaction": trigger_inputs.get("interaction", {}),
        "type": trigger_inputs.get("type"),
        "data": trigger_inputs.get("data", {}),
        "headers": trigger_inputs.get("headers", {}),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
    return output
