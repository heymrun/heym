from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.html_output_mapper_node import render_html_template

# The fields the editor offers as expressions besides `html` (chartOutputExpressionFields.ts,
# and the status and link fields of a table). `text` stays a static message: the docs say so,
# and a text widget's checkboxes edit it.
EXPRESSION_FIELDS = (
    "valueField",
    "dataPath",
    "statusColumn",
    "linkColumn",
    "linkLabel",
    "labelField",
    "xField",
    "yField",
    "min",
    "max",
    "unit",
    "title",
    "url",
)


def _resolve_expression_fields(ctx: NodeExecutionContext, node_data: dict) -> dict:
    """The node's settings with their ``$`` references filled in, as ``html`` is.

    Text that is not a reference, such as ``$5`` or ``$PATH``, stays as written; a number
    for a gauge's ``min`` or ``max`` is read as a number when the payload is built.
    """
    resolved = dict(node_data)
    for key in EXPRESSION_FIELDS:
        value = resolved.get(key)
        if isinstance(value, str) and "$" in value:
            resolved[key] = ctx.executor.evaluate_nonempty_message_template(
                value, ctx.inputs, ctx.node_id
            )
    return resolved


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the chartOutput node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    build_chart_payload = _workflow_executor.build_chart_payload
    self = ctx.executor
    if self.widget_action is not None and self.widget_action.node_id == ctx.node_id:
        return self.widget_action.output()
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
    node_data = _resolve_expression_fields(ctx, node_data)
    if node_data.get("chartType") == "html":
        node_data = {**node_data, "html": render_html_template(ctx)}
    output = build_chart_payload(node_data, source_data)
    if output.get("type") == "html":
        if self.widget_action is not None:
            output["html_action_node_id"] = self.widget_action.node_id
        elif ctx.node_id in self.widget_action_sources:
            output["html_action_node_id"] = ctx.node_id
    return output
