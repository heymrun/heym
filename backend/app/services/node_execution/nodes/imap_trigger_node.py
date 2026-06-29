from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the imapTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "email": trigger_inputs.get("email", {}),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
    return output
