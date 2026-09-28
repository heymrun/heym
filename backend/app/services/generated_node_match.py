"""Match a generated workflow's nodes to the versions they replace.

The chat builder returns a whole workflow. A node that already existed has the same id and
type or, failing that, the same label and type. The passes that keep a user's earlier
choices (credentials, data tables) use this to tell edited nodes from new ones.
"""

from __future__ import annotations

from typing import Any


def node_label(node: dict[str, Any]) -> str:
    """The node's label, or "" when it has none."""
    data = node.get("data")
    label = data.get("label") if isinstance(data, dict) else None
    return str(label) if label else ""


def previous_node_version(
    node: dict[str, Any], previous: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The node in `previous` that `node` replaces, or None for a new node."""
    node_type = node.get("type")
    for old in previous:
        if old.get("id") == node.get("id") and old.get("type") == node_type:
            return old
    label = node_label(node)
    if not label:
        return None
    for old in previous:
        if old.get("type") == node_type and node_label(old) == label:
            return old
    return None
