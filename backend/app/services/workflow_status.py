"""Derive a workflow's trigger status from its stored nodes.

The dashboard listing shows one status chip per workflow. Live run state ("running") comes
from the execution registry and deletion state from ``scheduled_for_deletion``; everything
else is a pure function of the node graph, so it is computed here and returned by every
endpoint that emits a ``WorkflowListResponse``.

A workflow with no trigger node is only "manual" until something calls it, unless its sole
terminal is an ``htmlOutputMapper`` - then it serves a page and reads "web". When the last run
came in over the HTTP API, from a parent workflow, or from the portal, the chip says so
instead - see ``refine_manual_status``.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.html_response import find_sole_html_terminal

TriggerStatus = Literal[
    "scheduled",
    "listening",
    "paused",
    "manual",
    "api",
    "subWorkflow",
    "portal",
    "web",
]

#: Nodes that start a workflow on their own, without a caller.
TRIGGER_NODE_TYPES: frozenset[str] = frozenset(
    {
        "cron",
        "telegramTrigger",
        "slackTrigger",
        "discordTrigger",
        "imapTrigger",
        "websocketTrigger",
        "fileUploadTrigger",
        "heymTrigger",
        "pluginTrigger",
        "rabbitmq",
    }
)


def _is_active(node: dict[str, Any]) -> bool:
    data = node.get("data")
    if not isinstance(data, dict):
        return True
    return data.get("active") is not False


def compute_trigger_status(
    nodes: list[Any] | None,
    edges: list[Any] | None = None,
) -> TriggerStatus:
    """Classify how a workflow starts.

    ``scheduled`` an active cron node exists, ``listening`` an active event trigger exists,
    ``paused`` trigger nodes exist but every one is deactivated, ``web`` no trigger nodes and
    the sole terminal serves an HTML page, ``manual`` no trigger nodes.
    """
    trigger_nodes = [
        node
        for node in nodes or []
        if isinstance(node, dict) and node.get("type") in TRIGGER_NODE_TYPES
    ]
    if not trigger_nodes:
        # Decided from the graph, so it short-circuits refine_manual_status: a page-serving
        # workflow should read WEB rather than API after its first HTTP call.
        if find_sole_html_terminal(nodes, edges):
            return "web"
        return "manual"

    active_nodes = [node for node in trigger_nodes if _is_active(node)]
    if not active_nodes:
        return "paused"

    if any(node.get("type") == "cron" for node in active_nodes):
        return "scheduled"

    return "listening"


#: ``execution_history.trigger_source`` values that replace the plain "manual" chip, lowercased.
MANUAL_TRIGGER_SOURCE_STATUSES: dict[str, TriggerStatus] = {
    "api": "api",
    "sub_workflow": "subWorkflow",
    "portal": "portal",
}


def refine_manual_status(status: TriggerStatus, last_trigger_source: str | None) -> TriggerStatus:
    """Narrow "manual" to how the workflow was last actually started.

    Only ``manual`` is refined: a workflow with trigger nodes keeps the chip its graph earns,
    and an unrecognised trigger source (cron, chat, board, an integration) stays ``manual``.
    """
    if status != "manual" or not last_trigger_source:
        return status
    return MANUAL_TRIGGER_SOURCE_STATUSES.get(last_trigger_source.strip().lower(), status)
