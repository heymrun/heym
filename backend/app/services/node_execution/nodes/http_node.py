from __future__ import annotations

import json
from importlib import import_module
from typing import Any

import httpx

from app.services.http_run_cookies import run_cookie_header, run_cookies
from app.services.node_execution.base import NodeExecutionContext

# What a redirect to another scheme, host or port still carries from the command's headers.
# Everything else (-H, -b, -u, a credential) stays with the origin the command named.
_CROSS_ORIGIN_HEADERS = frozenset({"accept", "content-type", "user-agent"})
# Set by httpx for each hop from its real body and URL: a 302 that turns a POST into a GET
# has no body, so the command's Content-Length must never be copied onto it.
_HOP_HEADERS = frozenset({"content-length", "transfer-encoding", "host"})
_MAX_REDIRECTS = 20


def _same_origin(first: httpx.URL, url: httpx.URL) -> bool:
    """Whether ``url`` is the command's own origin, counting an http to https upgrade.

    An upgrade on the same host with default ports keeps the headers, as on main.
    """
    if (url.scheme, url.host, url.port) == (first.scheme, first.host, first.port):
        return True
    return (
        first.scheme == "http"
        and url.scheme == "https"
        and url.host == first.host
        and first.port is None
        and url.port is None
    )


def _cookie_header(url: httpx.URL, command_cookie: str | None) -> str | None:
    """The cookies the server set for ``url`` in this run, then the `-b` cookies, as curl sends."""
    server_cookie = run_cookie_header(url)
    if not command_cookie:
        return server_cookie
    if not server_cookie:
        return command_cookie
    server_names = {part.split("=", 1)[0].strip() for part in server_cookie.split(";")}
    extra = [
        part.strip()
        for part in command_cookie.split(";")
        if part.strip() and part.split("=", 1)[0].strip() not in server_names
    ]
    return "; ".join([server_cookie, *extra])


def _send_following_redirects(
    client: httpx.Client,
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any,
    *,
    trusted: bool = False,
) -> httpx.Response:
    """Send the request and follow redirects (curl -L), one guarded hop at a time.

    httpx alone forwards every custom header to another origin except Authorization, so an
    API key in `-H` or a header credential reached the redirect target; and it drops the
    Cookie header on every hop. A hop to another origin now carries only
    `_CROSS_ORIGIN_HEADERS` from the command; a hop to the command's origin (again, after
    leaving it) gets every command header back, with the cookies the server set in this run
    and the `-b` cookie. `--location-trusted` sends the command headers to every hop, as
    curl does.
    """
    response = client.request(method, url, headers=headers, content=body, follow_redirects=False)
    first = response.request.url
    command_cookie = next(
        (value for key, value in headers.items() if key.lower() == "cookie"), None
    )
    for _ in range(_MAX_REDIRECTS):
        next_request = response.next_request
        if next_request is None:
            return response
        if trusted or _same_origin(first, next_request.url):
            for name, value in headers.items():
                if name.lower() != "cookie" and name.lower() not in _HOP_HEADERS:
                    next_request.headers[name] = value
            cookie = _cookie_header(next_request.url, command_cookie)
            if cookie:
                next_request.headers["Cookie"] = cookie
        else:
            for name in headers:
                if name.lower() not in _CROSS_ORIGIN_HEADERS | _HOP_HEADERS:
                    next_request.headers.pop(name, None)
        response.close()
        response = client.send(next_request, follow_redirects=False)
    raise httpx.TooManyRedirects("Exceeded maximum allowed redirects.", request=response.request)


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
    method, url, headers, body, follow_redirects, location_trusted = self.parse_curl(
        curl_template, resolve=render
    )
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
        if follow_redirects:
            response = _send_following_redirects(
                http_client, method, url, headers, body, trusted=location_trusted
            )
        else:
            response = http_client.request(
                method, url, headers=headers, content=body, follow_redirects=False
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
