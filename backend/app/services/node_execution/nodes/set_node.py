from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the set node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    mappings = node_data.get("mappings", [])
    result = {}
    for mapping in mappings:
        key = mapping.get("key", "")
        value_template = mapping.get("value", "")
        if key:
            if self._has_arithmetic(value_template):
                result[key] = self.resolve_arithmetic_expression(
                    value_template, inputs, node_id, preserve_type=True
                )
            elif self._is_single_dollar_expression(value_template):
                result[key] = self.resolve_expression(
                    value_template.strip(),
                    inputs,
                    node_id,
                    preserve_type=True,
                )
            elif "$" in value_template:
                result[key] = self._resolve_value_with_dollar_refs(value_template, inputs, node_id)
            else:
                result[key] = value_template
    output = result
    return output
