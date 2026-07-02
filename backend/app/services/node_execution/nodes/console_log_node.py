from __future__ import annotations

import logging

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the consoleLog node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data
    node_label = ctx.node_label

    log_message_template = node_data.get("logMessage", "$input")
    if log_message_template.startswith("$"):
        resolved = self.resolve_expression(
            log_message_template, inputs, node_id, preserve_type=True
        )
    else:
        resolved = self.evaluate_message_template(log_message_template, inputs, node_id)
    workflow_display = self._get_workflow_name_for_log()
    workflow_logger = logging.getLogger("heym.workflow")
    workflow_logger.info("[%s] [consoleLog:%s] %s", workflow_display, node_label, resolved)
    first_input = self._first_visible_input(inputs)
    output = first_input if isinstance(first_input, dict) else {"value": first_input}
    output = dict(output)
    output["logMessage"] = self._unwrap_value(resolved)
    return output
