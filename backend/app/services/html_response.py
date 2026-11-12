"""Decide whether a workflow run answers with an HTML page instead of a JSON body.

Both functions are pure: the API layer owns the request, the DB session, and the
``X-Simple-Response`` decision. This module only reads the graph and the node results.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import HTMLResponse

HTML_MAPPER_NODE_TYPE = "htmlOutputMapper"

#: Never counted when deciding whether a terminal is the *sole* terminal.
_NON_TERMINAL_TYPES = frozenset({"sticky", "errorHandler"})

#: A page is author-controlled content served from the instance's own origin. The
#: ``sandbox`` directive gives it an opaque origin, so its script cannot use the
#: visitor's session: no cookies, no localStorage, and no same-origin requests to the
#: Heym API. ``allow-same-origin`` is deliberately absent; adding it would undo that.
#: The header applies whatever ``contentType`` the node sets, because other types
#: (``image/svg+xml``, for one) run script too.
PAGE_CONTENT_SECURITY_POLICY = (
    "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox "
    "allow-modals allow-downloads allow-top-navigation-by-user-activation"
)

#: Headers sent with every page response.
PAGE_SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": PAGE_CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
}


def _is_active(node: dict[str, Any]) -> bool:
    data = node.get("data")
    if not isinstance(data, dict):
        return True
    return data.get("active") is not False


def find_sole_html_terminal(
    nodes: list[Any] | None,
    edges: list[Any] | None,
) -> str | None:
    """The node id when the only active terminal is an htmlOutputMapper, else None.

    Mirrors ``extract_output_node_from_workflow``'s notion of a terminal: a node no active
    edge leaves, ignoring sticky notes and error handlers.
    """
    node_list = [n for n in nodes or [] if isinstance(n, dict)]
    source_ids = {e.get("source") for e in edges or [] if isinstance(e, dict) and e.get("source")}

    terminals = [
        n
        for n in node_list
        if n.get("id") not in source_ids
        and _is_active(n)
        and n.get("type") not in _NON_TERMINAL_TYPES
    ]
    if len(terminals) != 1:
        return None

    sole = terminals[0]
    if sole.get("type") != HTML_MAPPER_NODE_TYPE:
        return None
    node_id = sole.get("id")
    return str(node_id) if node_id else None


def build_html_response(
    node_results: list[Any] | None,
    node_id: str,
) -> HTMLResponse | None:
    """Turn the html node's structured output into a response, or None if it produced none.

    Every response carries ``PAGE_SECURITY_HEADERS``, so the page runs sandboxed.
    """
    for row in node_results or []:
        if not isinstance(row, dict) or row.get("node_id") != node_id:
            continue
        if row.get("status") != "success":
            return None
        output = row.get("output")
        if not isinstance(output, dict) or "html" not in output:
            return None
        status_code = output.get("statusCode")
        return HTMLResponse(
            content=str(output.get("html") or ""),
            status_code=status_code if isinstance(status_code, int) else 200,
            media_type=str(output.get("contentType") or "text/html; charset=utf-8"),
            headers=dict(PAGE_SECURITY_HEADERS),
        )
    return None
