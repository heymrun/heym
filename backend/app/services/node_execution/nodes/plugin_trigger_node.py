from __future__ import annotations

from app.services import plugin_loader, plugin_store
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.plugin_node import _resolve_config, _safe_ctx


def execute(ctx: NodeExecutionContext) -> object:
    """Execute a `pluginTrigger` node by calling its handler's trigger()."""
    plugin_id = ctx.node_data.get("pluginId")
    if not plugin_id:
        raise ValueError("Plugin trigger node is missing pluginId")
    config = _resolve_config(ctx)
    result = plugin_loader.call_handler(
        plugin_id,
        plugin_store.plugins_root(),
        "trigger",
        {"config": config, "ctx": _safe_ctx(ctx)},
    )
    return result if isinstance(result, dict) else {"value": result}
