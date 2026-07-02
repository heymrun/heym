from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the sticky node."""
    node_data = ctx.node_data

    output = {"note": node_data.get("note", "")}
    return output
