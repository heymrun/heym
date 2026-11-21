from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def _with_field_defaults(body: dict, input_fields: object) -> dict:
    """The body with each Input field it leaves out set to that field's default value."""
    filled = dict(body)
    for field in input_fields if isinstance(input_fields, list) else []:
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if key and key not in filled and field.get("defaultValue"):
            filled[key] = field["defaultValue"]
    return filled


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the textInput node."""
    node_data = ctx.node_data

    initial_inputs = node_data.get("_initial_inputs", {})
    if initial_inputs:
        output = dict(initial_inputs)
        body = output.get("body")
        if isinstance(body, dict):
            body = _with_field_defaults(body, node_data.get("inputFields"))
            output["body"] = body
            output.update(body)
    else:
        default_value = node_data.get("value", "")
        if default_value:
            output = {"text": default_value}
        else:
            output = {}
    return output
