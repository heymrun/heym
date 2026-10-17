from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleDriveTrigger node: hand the detected file change downstream."""
    trigger_inputs = ctx.node_data.get("_initial_inputs") or {}
    change = trigger_inputs.get("change") or {}
    return {
        "event": change.get("event"),
        "file": change.get("file", {}),
        "changed_fields": change.get("changed_fields", []),
        "folder_id": change.get("folder_id"),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
