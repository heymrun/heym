from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the fileUploadTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    output = {
        "file": trigger_inputs.get("file", {}),
        "uploaded_at": trigger_inputs.get("uploaded_at"),
    }
    return output
