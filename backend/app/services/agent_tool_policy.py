"""Node types that may never become an agent tool.

Mirrors the frontend's ``BLOCKED_AS_TOOL_NODE_TYPES`` in
``frontend/src/lib/canvasConnectionRules.ts``. The canvas rule stops new connections; this
one covers workflows already saved with such an edge.
"""

from __future__ import annotations

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
