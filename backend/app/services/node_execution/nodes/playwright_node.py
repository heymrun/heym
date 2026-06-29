from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the playwright node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data
    node_label = ctx.node_label

    output = self._execute_playwright_node(node_data, inputs, node_id, node_label)
    return output
