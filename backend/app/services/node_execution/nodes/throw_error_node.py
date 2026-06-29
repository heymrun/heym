from __future__ import annotations

import time
from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the throwError node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    NodeResult = _workflow_executor.NodeResult  # noqa: N806
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    start_time = ctx.start_time
    node_type = ctx.node_type
    node_data = ctx.node_data
    node_label = ctx.node_label

    error_message_template = node_data.get("errorMessage", "")
    http_status_code = node_data.get("httpStatusCode")

    if error_message_template:
        error_message = self.evaluate_message_template(error_message_template, inputs, node_id)
    else:
        error_message = "Workflow error"

    execution_time = (time.time() - start_time) * 1000
    return NodeResult(
        node_id=node_id,
        node_label=node_label,
        node_type=node_type,
        status="error",
        output={"httpStatusCode": http_status_code} if http_status_code else {},
        execution_time_ms=execution_time,
        error=str(error_message),
    )
