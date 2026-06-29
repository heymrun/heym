from __future__ import annotations

from app.services import plugin_loader, plugin_store
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.plugin_node import (
    _resolve_config,
    _safe_ctx,
    resolve_node_function,
)


def execute(ctx: NodeExecutionContext) -> object:
    """Execute a `pluginTrigger` node by calling its handler function."""
    plugin_id = ctx.node_data.get("pluginId")
    if not plugin_id:
        raise ValueError("Plugin trigger node is missing pluginId")
    function_name = resolve_node_function(ctx, "trigger")
    config = _resolve_config(ctx)
    result = plugin_loader.call_handler(
        plugin_id,
        plugin_store.plugins_root(),
        function_name,
        {"config": config, "ctx": _safe_ctx(ctx)},
    )
    return result if isinstance(result, dict) else {"value": result}
