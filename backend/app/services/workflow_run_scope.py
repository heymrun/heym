"""Build an isolated graph for a canvas run ending at a selected node."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass
class WorkflowRunGraph:
    """Nodes and edges passed to the executor without changing the saved workflow."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def scope_workflow_run(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], target_id: str | None
) -> WorkflowRunGraph:
    """Keep the target, its ancestors, and their loop bodies and agent dependencies."""
    if target_id is None:
        return WorkflowRunGraph(nodes, edges)
    by_id = {node["id"]: node for node in nodes if node.get("type") != "sticky"}
    if target_id not in by_id:
        raise HTTPException(status_code=400, detail="Run target must be an executable node")

    # Cutting the target's forward edges also prevents a cycle from pulling later nodes in.
    candidates = [
        edge
        for edge in edges
        if edge["source"] in by_id and edge["target"] in by_id and edge["source"] != target_id
    ]
    included: set[str] = set()
    pending = [target_id]
    while pending:
        node_id = pending.pop()
        if node_id in included:
            continue
        included.add(node_id)
        node = by_id[node_id]
        pending.extend(
            edge["source"]
            for edge in candidates
            if edge["target"] == node_id and edge.get("targetHandle") != "loop"
        )
        if node.get("type") == "loop" and node_id != target_id:
            body_pending = [
                edge["target"]
                for edge in candidates
                if edge["source"] == node_id and edge.get("sourceHandle") == "loop"
            ]
            body_seen: set[str] = set()
            while body_pending:
                body_id = body_pending.pop()
                if body_id in body_seen or body_id == node_id:
                    continue
                body_seen.add(body_id)
                body_pending.extend(
                    edge["target"]
                    for edge in candidates
                    if edge["source"] == body_id and edge.get("targetHandle") != "loop"
                )
            if target_id not in body_seen:
                pending.extend(body_seen)
        data = node.get("data") or {}
        if node.get("type") == "agent" and data.get("isOrchestrator"):
            labels = set(data.get("subAgentLabels") or [])
            pending.extend(
                sub_id
                for sub_id, sub in by_id.items()
                if sub.get("type") == "agent" and sub.get("data", {}).get("label") in labels
            )

    return WorkflowRunGraph(
        deepcopy([node for node in nodes if node["id"] in included]),
        deepcopy(
            [
                edge
                for edge in candidates
                if edge["source"] in included and edge["target"] in included
            ]
        ),
    )
