from __future__ import annotations

from typing import Any

DASHBOARD_WIDGET_BLOCKED_NODE_TYPES: frozenset[str] = frozenset(
    {
        "textInput",
        "cron",
        "telegramTrigger",
        "slackTrigger",
        "discordTrigger",
        "imapTrigger",
        "websocketTrigger",
        "fileUploadTrigger",
        "rabbitmq",
        "errorHandler",
        "pluginTrigger",
    }
)


def find_blocked_dashboard_widget_nodes(nodes: list[dict[str, Any]] | None) -> list[str]:
    """Return display names for nodes that dashboard widgets are not allowed to run."""
    blocked: list[str] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type not in DASHBOARD_WIDGET_BLOCKED_NODE_TYPES:
            continue
        data = node.get("data")
        label = data.get("label") if isinstance(data, dict) else None
        if label:
            blocked.append(f"{label} ({node_type})")
        else:
            blocked.append(str(node_type))
    return blocked


def dashboard_widget_blocked_nodes_error(nodes: list[dict[str, Any]] | None) -> str | None:
    """Return a validation error when a dashboard widget contains trigger-like nodes."""
    blocked = find_blocked_dashboard_widget_nodes(nodes)
    if not blocked:
        return None
    return (
        "Dashboard widget workflows cannot include trigger/input nodes: "
        f"{', '.join(blocked)}. Use data-producing nodes and end with chartOutput."
    )
