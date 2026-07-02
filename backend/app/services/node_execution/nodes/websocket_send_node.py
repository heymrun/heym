from __future__ import annotations

from importlib import import_module
from typing import Any

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the websocketSend node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _is_single_dollar_expression = _workflow_executor._is_single_dollar_expression
    run_async = _workflow_executor.run_async
    send_websocket_message = _workflow_executor.send_websocket_message
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    url_template = str(node_data.get("websocketUrl", "") or "").strip()
    if not url_template:
        raise ValueError("WebSocket Send node requires a URL")

    url = self.evaluate_message_template(url_template, inputs, node_id).strip()
    if not url:
        raise ValueError("WebSocket Send node requires a URL")

    headers_template = str(node_data.get("websocketHeaders", "") or "").strip()
    if headers_template and _is_single_dollar_expression(headers_template):
        resolved_headers: Any = self.resolve_expression(
            headers_template,
            inputs,
            node_id,
            preserve_type=True,
        )
    elif headers_template:
        resolved_headers = self.evaluate_message_template(
            headers_template,
            inputs,
            node_id,
        )
    else:
        resolved_headers = {}

    subprotocols_template = str(node_data.get("websocketSubprotocols", "") or "").strip()
    if subprotocols_template and _is_single_dollar_expression(subprotocols_template):
        resolved_subprotocols: Any = self.resolve_expression(
            subprotocols_template,
            inputs,
            node_id,
            preserve_type=True,
        )
    elif subprotocols_template:
        resolved_subprotocols = self.evaluate_message_template(
            subprotocols_template,
            inputs,
            node_id,
        )
    else:
        resolved_subprotocols = []

    message_template = node_data.get("websocketMessage", "$input")
    if isinstance(message_template, str) and _is_single_dollar_expression(message_template.strip()):
        resolved_message = self.resolve_expression(
            message_template.strip(),
            inputs,
            node_id,
            preserve_type=True,
        )
    else:
        resolved_message = self.evaluate_message_template(
            str(message_template),
            inputs,
            node_id,
        )

    output = run_async(
        send_websocket_message(
            url=url,
            headers=resolved_headers,
            subprotocols=resolved_subprotocols,
            message=resolved_message,
        )
    )
    return output
