"""Resolution of the optional per-node ``extraBody`` payload for llm and agent nodes.

Both node types let an author attach provider-specific request parameters (for example
``{"thinking": {"type": "disabled"}}``) to the LLM API calls they make. Parsing lives here
so the two handlers share one validation path instead of drifting apart.
"""

from __future__ import annotations

import json
from typing import Any


def resolve_extra_body(
    executor: Any, node_data: dict, inputs: dict, node_id: str | None
) -> dict[str, Any] | None:
    """Return the parsed extra body for a node, or ``None`` when it is not configured.

    ``$`` expressions are resolved before parsing, which means the text must still form a
    valid JSON object afterwards. Invalid input raises ``ValueError`` so the node fails
    loudly instead of silently dropping the configuration.
    """
    if not node_data.get("extraBodyEnabled"):
        return None
    raw = str(node_data.get("extraBody") or "").strip()
    if not raw:
        return None

    resolved = executor._resolve_template(raw, inputs, node_id or "").strip()
    if not resolved:
        return None

    try:
        parsed = json.loads(resolved)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid extra body JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Extra body must be a JSON object, got {type(parsed).__name__}")
    return parsed
