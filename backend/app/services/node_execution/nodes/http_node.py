from __future__ import annotations

import json
from importlib import import_module
from typing import Any

from app.services.http_run_cookies import run_cookies
from app.services.node_execution.base import NodeExecutionContext


def _json_media_type(headers: dict[str, str]) -> str | None:
    """The request's JSON media type, or None when the body is not declared as JSON.

    That is `application/json` and the RFC 6839 `+json` types (`application/vnd.api+json`,
    `application/merge-patch+json`, ...), which carry the same JSON.
    """
    for key, value in headers.items():
        if key.lower() == "content-type":
            media_type = value.split(";", 1)[0].strip().lower()
            if media_type == "application/json" or (
                media_type.startswith("application/") and media_type.endswith("+json")
            ):
                return media_type
            return None
    return None


def _is_json_text(value: str) -> bool:
    """Return whether a string is a complete JSON document."""
    try:
        json.loads(value)
    except ValueError:
        return False
    return True


def _is_inside_json_string(text: str, position: int) -> bool:
    """Return whether a position is inside a double-quoted JSON string."""
    in_string = False
    escaped = False
    for char in text[:position]:
        if escaped:
            escaped = False
        elif in_string and char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
    return in_string


def _json_literal(value: object) -> str:
    """Encode a resolved expression as a JSON value."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def _render_json_body_template(
    executor: Any,
    body: str,
    inputs: dict,
    node_id: str,
    *,
    keep_json_text: bool = False,
) -> str:
    """Resolve JSON-body expressions with JSON-safe serialization.

    With ``keep_json_text``, a string outside quotes that is itself JSON goes in as it is,
    which is how the `+json` types were rendered before they got JSON-safe values.
    """
    rendered: list[str] = []
    last_end = 0
    for start, end, expression in executor._find_expressions(body):
        rendered.append(body[last_end:start])
        value = executor.resolve_expression(expression, inputs, node_id, preserve_type=True)
        if _is_inside_json_string(body, start):
            replacement = _json_literal(str(value))[1:-1]
        elif expression.endswith(".escape()") and isinstance(value, str):
            replacement = value
        elif keep_json_text and isinstance(value, str) and _is_json_text(value):
            replacement = value
        else:
            replacement = _json_literal(value)
        rendered.append(replacement)
        last_end = end
    rendered.append(body[last_end:])
    return "".join(rendered)


def _shown_request_headers(headers: Any) -> dict[str, str]:
    """The sent headers for the node output, with a Basic credential hidden.

    A Basic value is base64 of `user:password` (`curl -u`), which credential masking,
    a search for the secret itself, cannot recognise in persisted output.
    """
    shown = dict(headers)
    for key, value in shown.items():
        if key.lower() == "authorization" and value[:6].lower() == "basic ":
            shown[key] = "Basic **"
    return shown


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the http node."""
    ssrf_guard = import_module("app.services.ssrf_guard")
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    curl_template = node_data.get("curl", "")

    def render(text: str) -> str:
        return self.evaluate_message_template(text, inputs, node_id)

    # Resolve while parsing: an expression can supply a whole header line or the
    # whole URL, and parsing the raw template would drop it. The body is left raw
    # so it can be rendered JSON-aware below.
    method, url, headers, body, follow_redirects = self.parse_curl(curl_template, resolve=render)
    if not url:
        raise ValueError("HTTP node requires a URL")
    # Refuse targets that resolve to internal/metadata addresses before dialing
    # (SSRF, GHSA-8wj7-v2w6-wfcx). The guarded client additionally pins the
    # resolved IP so redirects and DNS rebinding cannot reach internal hosts.
    ssrf_guard.guard_http_url(url)
    if body:
        media_type = _json_media_type(headers)
        if media_type is not None:
            body = _render_json_body_template(
                self,
                body,
                inputs,
                node_id,
                # Existing `+json` workflows may pass JSON text through an expression.
                keep_json_text=media_type != "application/json",
            )
        else:
            body = self.evaluate_message_template(body, inputs, node_id)
    http_client = ssrf_guard.get_guarded_http_client()
    with run_cookies(self.http_cookies):
        response = http_client.request(
            method,
            url,
            headers=headers,
            content=body,
            follow_redirects=follow_redirects,
        )
    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text
    output = {
        "status": response.status_code,
        "headers": dict(response.headers),
        "body": response_body,
        "request": {
            "method": method,
            "url": str(response.request.url),
            "headers": _shown_request_headers(response.request.headers),
        },
    }
    return output
