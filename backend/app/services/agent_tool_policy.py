"""Node types that may never become an agent tool.

Mirrors the frontend's ``BLOCKED_AS_TOOL_NODE_TYPES`` in
``frontend/src/lib/canvasConnectionRules.ts``. The canvas rule stops new connections; this
one covers workflows already saved with such an edge.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

TOOL_INPUT_HANDLE = "tool-input"
_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")

#: Terminal mappers. Called mid-conversation they produce a response body nothing reads.
BLOCKED_AS_TOOL_NODE_TYPES: frozenset[str] = frozenset(
    {
        "jsonOutputMapper",
        "htmlOutputMapper",
    }
)


def is_blocked_as_tool(node_type: str | None) -> bool:
    """True when a node of this type must not be exposed to an agent as a tool."""
    return bool(node_type) and node_type in BLOCKED_AS_TOOL_NODE_TYPES


@dataclass(frozen=True)
class NodeTool:
    """A canvas node an agent can call: ``name`` is what the agent and its traces use."""

    node_id: str
    name: str
    label: str


def slugify_tool_name(label: str) -> str:
    slug = _SLUG_RE.sub("_", label.strip()).strip("_").lower()
    return slug[:64] or "node_tool"


def node_tools_for_agent(
    nodes: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    agent_node_id: str,
) -> list[NodeTool]:
    """The nodes on the agent's tool-input handle, in edge order, with the tool names the
    executor gives them: a repeated name gets ``_2``, ``_3`` and so on.

    ``nodes`` is a workflow's node list or, as the executor keeps it, a map of id to node.
    """
    by_id = (
        nodes
        if isinstance(nodes, Mapping)
        else {node.get("id"): node for node in nodes if isinstance(node, dict)}
    )
    tools: list[NodeTool] = []
    seen_names: set[str] = set()
    for edge in edges:
        if edge.get("target") != agent_node_id or edge.get("targetHandle") != TOOL_INPUT_HANDLE:
            continue
        node_id = edge.get("source")
        node = by_id.get(node_id)
        if node is None or is_blocked_as_tool(node.get("type")):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        label = data.get("label") or node_id
        base_name = slugify_tool_name(label)
        name = base_name
        suffix = 2
        while name in seen_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        seen_names.add(name)
        tools.append(NodeTool(node_id=node_id, name=name, label=label))
    return tools
