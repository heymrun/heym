from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the mcpCall node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.services.mcp_tool_executor import execute_mcp_tool

    mcp_connection = node_data.get("connection") or {}
    selected_tool = node_data.get("selectedTool") or ""
    tool_arguments = node_data.get("toolArguments") or {}
    timeout = float(node_data.get("timeoutSeconds") or 30)

    if not selected_tool:
        raise ValueError("mcpCall node requires a tool to be selected")

    mcp_connection = self._resolve_mcp_connection(mcp_connection, inputs, node_id)

    resolved_args = self._resolve_mcp_config_value(
        tool_arguments,
        inputs,
        node_id,
    )

    mcp_result = execute_mcp_tool(mcp_connection, selected_tool, resolved_args, timeout)
    output = {"result": mcp_result}
    return output
