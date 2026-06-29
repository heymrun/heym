from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the chartOutput node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    build_chart_payload = _workflow_executor.build_chart_payload
    self = ctx.executor
    inputs = ctx.inputs
    node_data = ctx.node_data

    visible_inputs = self._visible_inputs(inputs)
    if len(visible_inputs) == 1:
        source_data = next(iter(visible_inputs.values()))
    elif visible_inputs:
        merged: dict = {}
        for value in visible_inputs.values():
            if isinstance(value, dict):
                merged.update(value)
        source_data = merged
    else:
        source_data = {}
    output = build_chart_payload(node_data, source_data)
    return output
