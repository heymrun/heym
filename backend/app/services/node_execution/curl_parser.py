"""The HTTP node's cURL template, parsed into the request it describes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def parse_curl(
    executor: Any,
    curl_command: str,
    resolve: Callable[[str], str] | None = None,
) -> tuple[str, str, dict[str, str], str | None, bool]:
    """Parse a curl DSL command into its request parts.

    ``resolve`` renders ``$…`` spans in every token except the ``-d`` payload,
    which callers render themselves so JSON bodies keep their types. It must be
    applied before the token is interpreted: a header-type credential resolves to
    a whole ``key: value`` line and a URL can come entirely from an expression,
    so parsing the raw template would drop the header and lose the URL.
    """
    if not curl_command:
        return "GET", "", {}, None, False
    normalized_cmd = curl_command.replace("\\\n", " ").replace("\\\r\n", " ")
    masked_cmd, masked_expressions = executor._mask_curl_expressions(normalized_cmd)
    tokens = [
        executor._unmask_curl_expressions(token, masked_expressions)
        for token in executor._split_curl_tokens(masked_cmd)
    ]
    if tokens and tokens[0].lower() == "curl":
        tokens = tokens[1:]

    def rendered(token: str) -> str:
        if resolve is None or "$" not in token:
            return token
        return resolve(token)

    method = "GET"
    headers: dict[str, str] = {}
    data = None
    url = ""
    follow_redirects = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("-X", "--request") and i + 1 < len(tokens):
            i += 1
            method = rendered(tokens[i]).upper()
        elif token in ("-H", "--header") and i + 1 < len(tokens):
            i += 1
            header = rendered(tokens[i])
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip()] = value.strip()
        elif token in ("-L", "--location"):
            follow_redirects = True
        elif token in (
            "-d",
            "--data",
            "--data-raw",
            "--data-binary",
            "--data-urlencode",
        ) and i + 1 < len(tokens):
            i += 1
            data = tokens[i]
            if method == "GET":
                method = "POST"
        elif token == "--url" and i + 1 < len(tokens):
            i += 1
            url = rendered(tokens[i])
        elif not token.startswith("-"):
            candidate = rendered(token)
            if candidate.startswith(("http://", "https://")):
                url = candidate
        i += 1

    if not url:
        for token in reversed(tokens):
            if token is data:
                continue
            candidate = rendered(token)
            if candidate.startswith(("http://", "https://")):
                url = candidate
                break

    return method, url, headers, data, follow_redirects
