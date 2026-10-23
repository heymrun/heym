"""Which workflow, and which step of it, a HITL dashboard widget shows reviews from.

The choice lives on the widget workflow's HITL ``chartOutput`` node as ``hitlWorkflowId`` and
``hitlNodeId``, so Settings, AI fine-tune and the canvas all edit one place. Neither field
grants anything: the inbox still returns only reviews in the viewer's review scope
(``hitl_service.review_scope_clause``), and every read re-checks that the chosen workflow is in
it. This module has no database or settings imports, so dashboards can read the filter cheaply.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass

# The Slack node's operations that pause the run as a review. Kept here rather than imported
# from slack_operations, which pulls in the node runtime; a test keeps the two equal.
WAITING_SLACK_OPERATIONS = frozenset({"requestApproval", "sendButtons", "sendForm"})

WORKFLOW_FIELD = "hitlWorkflowId"
NODE_FIELD = "hitlNodeId"

# Shown instead of the widget's reviews when its workflow is out of the viewer's scope. The
# workflow is never named: a deleted workflow and someone else's look the same.
HITL_FILTER_ACCESS_ERROR = (
    "You no longer have access to the workflow this widget shows. "
    "Pick another one in widget Settings."
)
HITL_FILTER_READ_ONLY_ACCESS_ERROR = "You do not have access to the workflow this widget shows."


@dataclass(frozen=True)
class HitlWidgetFilter:
    """Reviews from one workflow; from one of its steps when ``node_id`` is set."""

    workflow_id: uuid.UUID
    node_id: str | None = None


def _node_data(node: object) -> dict:
    if not isinstance(node, dict):
        return {}
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def review_step_kind(node: object) -> str | None:
    """``"agent"`` or ``"slack"`` when the node can leave a review waiting, else None."""
    if not isinstance(node, dict):
        return None
    data = _node_data(node)
    node_type = node.get("type")
    if node_type == "agent" and data.get("hitlEnabled"):
        return "agent"
    if node_type == "slack" and data.get("slackOperation") in WAITING_SLACK_OPERATIONS:
        return "slack"
    return None


def review_steps(nodes: object) -> list[tuple[str, str, str]]:
    """``(node_id, label, kind)`` of every step in ``nodes`` that can wait, in graph order."""
    if not isinstance(nodes, list):
        return []
    steps: list[tuple[str, str, str]] = []
    for node in nodes:
        kind = review_step_kind(node)
        node_id = str(node.get("id") or "").strip() if kind else ""
        if kind and node_id:
            label = str(_node_data(node).get("label") or "").strip() or node_id
            steps.append((node_id, label, kind))
    return steps


def _hitl_chart(nodes: object) -> dict | None:
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and node.get("type") == "chartOutput":
            if _node_data(node).get("chartType") == "hitl":
                return node
    return None


def _filter_from_data(data: dict) -> HitlWidgetFilter | None:
    raw_workflow = str(data.get(WORKFLOW_FIELD) or "").strip()
    if not raw_workflow:
        return None
    try:
        workflow_id = uuid.UUID(raw_workflow)
    except ValueError:
        return None
    node_id = str(data.get(NODE_FIELD) or "").strip() or None
    return HitlWidgetFilter(workflow_id=workflow_id, node_id=node_id)


def hitl_widget_filter(nodes: object) -> HitlWidgetFilter | None:
    """The filter on a widget workflow's HITL chart, or None when it shows every review."""
    chart = _hitl_chart(nodes)
    return _filter_from_data(_node_data(chart)) if chart is not None else None


def with_hitl_widget_filter(nodes: list, value: HitlWidgetFilter | None) -> list:
    """A copy of ``nodes`` whose HITL chart shows ``value``; None clears the filter."""
    updated = copy.deepcopy(nodes)
    chart = _hitl_chart(updated)
    if chart is None:
        return updated
    data = dict(_node_data(chart))
    data.pop(WORKFLOW_FIELD, None)
    data.pop(NODE_FIELD, None)
    if value is not None:
        data[WORKFLOW_FIELD] = str(value.workflow_id)
        if value.node_id:
            data[NODE_FIELD] = value.node_id
    chart["data"] = data
    return updated


def strip_hitl_widget_filter(nodes: list) -> list:
    """A copy of ``nodes`` with the filter fields removed from every chart node."""
    updated = copy.deepcopy(nodes)
    for node in updated:
        if isinstance(node, dict) and node.get("type") == "chartOutput":
            data = _node_data(node)
            data.pop(WORKFLOW_FIELD, None)
            data.pop(NODE_FIELD, None)
    return updated


def hitl_filter_changed(old_nodes: object, new_nodes: object) -> bool:
    """True when a save points the widget at different reviews than before."""
    return hitl_widget_filter(old_nodes) != hitl_widget_filter(new_nodes)
