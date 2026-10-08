"""What a workflow asks for when someone runs it by hand: the fields of its start nodes.

Shared by the run forms (Quick Drawer, the dashboard run widget) so every surface offers
the same fields.
"""

from typing import Any


def start_input_fields(
    nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """The fields of the active textInput nodes nothing feeds into, as {key, defaultValue}.

    A textInput node without configured fields takes one, ``text``.
    """
    target_ids = {edge.get("target") for edge in edges or [] if edge.get("target")}
    fields: list[dict[str, Any]] = []
    for node in nodes or []:
        data = node.get("data") or {}
        if (
            node.get("id") in target_ids
            or node.get("type") != "textInput"
            or data.get("active") is False
        ):
            continue
        for field in data.get("inputFields") or [{"key": "text"}]:
            fields.append(
                {"key": field.get("key", "text"), "defaultValue": field.get("defaultValue")}
            )
    return fields
