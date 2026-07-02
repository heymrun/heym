from __future__ import annotations

import json

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the output node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    output_schema = node_data.get("outputSchema", [])
    if output_schema and len(output_schema) > 0:
        result = {}
        for field in output_schema:
            key = field.get("key", "")
            value_template = field.get("value", "")
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
                    result[key] = self._resolve_value_with_dollar_refs(
                        value_template,
                        inputs,
                        node_id,
                        preserve_type=True,
                    )
                else:
                    result[key] = value_template
        output = {"result": result}
    else:
        message_template = node_data.get("message", "")
        if message_template:
            if self._has_arithmetic(message_template):
                result_value = self.resolve_arithmetic_expression(message_template, inputs, node_id)
            elif self._is_single_dollar_expression(message_template):
                result_value = self.resolve_expression(
                    message_template.strip(),
                    inputs,
                    node_id,
                    preserve_type=True,
                )
            elif "$" in message_template:
                result_value = self._resolve_value_with_dollar_refs(
                    message_template,
                    inputs,
                    node_id,
                    preserve_type=True,
                )
                if (
                    isinstance(result_value, str)
                    and result_value.startswith('"')
                    and result_value.endswith('"')
                    and len(result_value) >= 2
                ):
                    try:
                        parsed = json.loads(result_value)
                        if isinstance(parsed, str):
                            result_value = parsed
                    except (json.JSONDecodeError, ValueError):
                        pass
            else:
                result_value = message_template
            output = {"result": result_value}
        else:
            output = {"result": inputs}
    return output
