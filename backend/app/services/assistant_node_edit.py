"""Canvas AI Assistant turns scoped to one node.

The AI button on a canvas node opens the assistant focused on that node. In Agent mode
the model returns only that node and the editor updates it in place, leaving every other
node, edge and position untouched. In Ask mode the focus only tells the model which node
the question is about.
"""

from typing import Any

NODE_EDIT_TRACE_NODE_LABEL = "AI Builder (Node)"


def find_workflow_node(current_workflow: dict | None, node_id: str | None) -> dict | None:
    """Return the node with ``node_id`` from the request's workflow, or None."""
    if not current_workflow or not node_id:
        return None
    nodes = current_workflow.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return None


def _node_identity(node: dict[str, Any]) -> tuple[str, str, str]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    label = str(data.get("label") or node.get("id") or "")
    return str(node.get("id") or ""), str(node.get("type") or ""), label


def build_node_edit_prompt(
    current_workflow: dict | None,
    target_node_id: str | None,
    *,
    ask_mode: bool,
) -> str:
    """Prompt section for a turn focused on one node; empty when the node is not in the workflow."""
    node = find_workflow_node(current_workflow, target_node_id)
    if node is None:
        return ""
    node_id, node_type, label = _node_identity(node)

    if ask_mode:
        return (
            "\n\n## Node in Focus\n"
            f"The user opened the assistant from the node `{label}` (type `{node_type}`, "
            f"id `{node_id}`). Answer about that node unless the question is clearly about "
            "something else.\n"
        )

    return f"""

## Node Edit Mode

The user opened the assistant from the node `{label}` (type `{node_type}`, id `{node_id}`).
This turn changes that node only. These rules override any instruction above to return the
complete workflow, in YOLO mode too.

- Return exactly one fenced ```json block holding `{{"nodes": [<the node>], "edges": []}}`:
  the node with the same `id`, `type` and `data.label`, and its complete `data` after the
  change. Keep every field the request does not touch.
- Never add, remove, rename or reconnect nodes. The editor applies only this node; anything
  else in the block is ignored.
- Reference other nodes' outputs with the usual `$label` expressions; their labels do not
  change.
- When asked to fix an error, read this node's entry in the execution log and fix the cause
  in this node's configuration.
- When the request cannot be done inside this node (it needs another node type, a new node
  or changes to other nodes), return no JSON. Say in one or two sentences what would have
  to change, and that closing the node focus lets the assistant edit the whole workflow.
- `heym-clarify` questions work as usual.
"""
