from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext

DEFAULT_CONTENT_TYPE = "text/html; charset=utf-8"


def _coerce_status_code(raw: object) -> int:
    """HTTP status codes outside 100-599 would make Starlette raise mid-response."""
    try:
        code = int(str(raw).strip())
    except (TypeError, ValueError):
        return 200
    if code < 100 or code > 599:
        return 200
    return code


def render_html_template(ctx: NodeExecutionContext) -> str:
    """The node's ``html`` template with its ``$`` expressions filled in.

    Shared with the chartOutput node's ``html`` chart type, so a widget's HTML and a page's
    HTML resolve expressions the same way.
    """
    template = str(ctx.node_data.get("html") or "")
    return ctx.executor.evaluate_nonempty_message_template(template, ctx.inputs, ctx.node_id)


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the htmlOutputMapper node."""
    node_data = ctx.node_data
    html = render_html_template(ctx)

    content_type = str(node_data.get("contentType") or "").strip() or DEFAULT_CONTENT_TYPE

    return {
        "html": html,
        "statusCode": _coerce_status_code(node_data.get("statusCode")),
        "contentType": content_type,
    }
