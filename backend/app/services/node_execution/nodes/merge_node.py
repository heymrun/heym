from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the merge node."""
    self = ctx.executor
    inputs = ctx.inputs

    merged_data = {}
    for label, data in self._visible_inputs(inputs).items():
        if isinstance(data, dict):
            merged_data[label] = data
        else:
            merged_data[label] = {"value": data}
    output = {"merged": merged_data}
    return output
