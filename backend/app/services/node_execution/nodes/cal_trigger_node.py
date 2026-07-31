from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Expose a verified Cal.com webhook to downstream nodes."""
    trigger_inputs = ctx.node_data.get("_initial_inputs", {})
    return {
        "event": trigger_inputs.get("event", {}),
        "triggerEvent": trigger_inputs.get("trigger_event"),
        "payload": trigger_inputs.get("payload", {}),
        "headers": trigger_inputs.get("headers", {}),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
