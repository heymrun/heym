from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the slackTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "event": trigger_inputs.get("event", {}),
        "headers": trigger_inputs.get("headers", {}),
    }
    return output
