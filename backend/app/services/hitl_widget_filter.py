"""Which workflow, and which step of it, a HITL dashboard widget shows reviews from.

The choice lives on the widget workflow's HITL ``chartOutput`` node as ``hitlWorkflowId`` and
``hitlNodeId``, so Settings, AI fine-tune and the canvas all edit one place. Neither field
grants anything: every read re-checks that the viewer can open the chosen workflow
(``hitl_service.review_access_clause``). This module has no database or settings imports, so
dashboards can read the filter cheaply.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

# The Slack node's operations that pause the run as a review. Kept here rather than imported
# from slack_operations, which pulls in the node runtime; a test keeps the two equal.
WAITING_SLACK_OPERATIONS = frozenset({"requestApproval", "sendButtons", "sendForm"})

WORKFLOW_FIELD = "hitlWorkflowId"
NODE_FIELD = "hitlNodeId"

# Shown to the dashboard's owner instead of the widget's reviews when they can no longer open
# its workflow; anyone else who cannot open it does not see the widget. The workflow is never
# named: a deleted workflow and someone else's look the same.
HITL_FILTER_ACCESS_ERROR = (
    "You no longer have access to the workflow this widget shows. "
    "Pick another one in widget Settings."
)


@dataclass(frozen=True)
class HitlWidgetFilter:
    """Reviews from one workflow; from one of its steps when ``node_id`` is set."""

    workflow_id: uuid.UUID
    node_id: str | None = None


@dataclass(frozen=True)
class ReviewStep:
    """A step that can leave a review waiting: an agent or a Slack approval, button or form."""

    node_id: str
    label: str
    kind: str


@dataclass(frozen=True)
class ReviewSource:
    """A workflow a HITL widget can show reviews from, with its waiting steps."""

    workflow_id: uuid.UUID
    workflow_name: str
    steps: tuple[ReviewStep, ...]


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


def review_steps(nodes: object) -> list[ReviewStep]:
    """Every step in ``nodes`` that can leave a review waiting, in graph order."""
    if not isinstance(nodes, list):
        return []
    steps: list[ReviewStep] = []
    for node in nodes:
        kind = review_step_kind(node)
        node_id = str(node.get("id") or "").strip() if kind else ""
        if kind and node_id:
            label = str(_node_data(node).get("label") or "").strip() or node_id
            steps.append(ReviewStep(node_id=node_id, label=label, kind=kind))
    return steps


def _hitl_chart(nodes: object) -> dict | None:
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and node.get("type") == "chartOutput":
            if _node_data(node).get("chartType") == "hitl":
                return node
    return None


def filter_from_chart_data(data: dict) -> HitlWidgetFilter | None:
    """The filter set on one HITL chart node's data, or None."""
    raw_workflow = str(data.get(WORKFLOW_FIELD) or "").strip()
    if not raw_workflow:
        return None
    try:
        workflow_id = uuid.UUID(raw_workflow)
    except ValueError:
        return None
    node_id = str(data.get(NODE_FIELD) or "").strip() or None
    return HitlWidgetFilter(workflow_id=workflow_id, node_id=node_id)


def has_hitl_chart(nodes: object) -> bool:
    """True when the graph ends in the pending-review inbox chart."""
    return _hitl_chart(nodes) is not None


def hitl_widget_filter(nodes: object) -> HitlWidgetFilter | None:
    """The filter on a widget workflow's HITL chart, or None when it shows every review."""
    chart = _hitl_chart(nodes)
    return filter_from_chart_data(_node_data(chart)) if chart is not None else None


def filter_payload(value: HitlWidgetFilter) -> dict[str, str | None]:
    """The filter as a HITL chart payload carries it to the carousel."""
    return {"workflow_id": str(value.workflow_id), "node_id": value.node_id}


def filter_from_payload(payload: object) -> HitlWidgetFilter | None:
    """The filter a HITL chart payload carries, or None for any other payload."""
    if not isinstance(payload, dict) or payload.get("type") != "hitl":
        return None
    raw = payload.get("filter")
    if not isinstance(raw, dict):
        return None
    return filter_from_chart_data(
        {WORKFLOW_FIELD: raw.get("workflow_id"), NODE_FIELD: raw.get("node_id")}
    )


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


def hitl_filter_changed(old_nodes: object, new_nodes: object) -> bool:
    """True when a save points the widget at different reviews than before."""
    return hitl_widget_filter(old_nodes) != hitl_widget_filter(new_nodes)


def pending_for_widgets(
    own: dict[tuple[uuid.UUID, str], int],
    chosen: dict[tuple[uuid.UUID, str], int],
    filters: Sequence[HitlWidgetFilter | None],
) -> int:
    """Pending reviews a page's HITL widgets show together, each review counted once.

    ``own`` counts the viewer's own queue, which an unfiltered widget shows; ``chosen`` counts
    the filtered workflows the viewer can open, by ``(workflow_id, node_id)``. A filter on a
    workflow the viewer cannot open matches nothing in ``chosen``.
    """
    shown: set[tuple[uuid.UUID, str]] = set(own) if any(f is None for f in filters) else set()
    for value in filters:
        if value is not None:
            shown |= {
                key
                for key in chosen
                if key[0] == value.workflow_id and value.node_id in (None, key[1])
            }
    counts = {**own, **chosen}
    return sum(counts[key] for key in shown)
