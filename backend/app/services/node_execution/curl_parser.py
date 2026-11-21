"""The HTTP node's cURL template, parsed into the request it describes."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

# Options that set one header. A header the command also sets with -H wins, as in curl.
_HEADER_OPTIONS = {
    "-A": "User-Agent",
    "--user-agent": "User-Agent",
    "-b": "Cookie",
    "--cookie": "Cookie",
    "-e": "Referer",
    "--referer": "Referer",
}


def _url_encoded(value: str) -> str:
    """A --data-urlencode piece as curl sends it: the content after the first "=" encoded.

    `name=content` keeps the name, `=content` and `content` send the content alone.
    """
    if "=" not in value:
        return quote(value, safe="")
    name, content = value.split("=", 1)
    return (f"{name}=" if name else "") + quote(content, safe="")


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
    basic_user: str | None = None
    json_option = False
    data_indexes: set[int] = set()
    explicit_method = False
    get_option = False
    head_option = False
    option_headers: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("-X", "--request") and i + 1 < len(tokens):
            i += 1
            method = rendered(tokens[i]).upper()
            explicit_method = True
        elif token in ("-G", "--get"):
            get_option = True
        elif token in ("-H", "--header") and i + 1 < len(tokens):
            i += 1
            header = rendered(tokens[i])
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip()] = value.strip()
        elif token in _HEADER_OPTIONS and i + 1 < len(tokens):
            # Consumed here so the value (a Referer is a URL) is never taken as the URL.
            i += 1
            value = rendered(tokens[i])
            # `-b name` without "=" names a cookie file, which a workflow cannot read.
            if token not in ("-b", "--cookie") or "=" in value:
                option_headers[_HEADER_OPTIONS[token]] = value
        elif token in ("-x", "--proxy", "--preproxy") and i + 1 < len(tokens):
            # The node connects directly. Consumed so the proxy address is never the URL.
            i += 1
        elif token in ("-I", "--head"):
            head_option = True
        elif token in ("-L", "--location"):
            follow_redirects = True
        elif token in ("-u", "--user") and i + 1 < len(tokens):
            # How Stripe, Twilio and Mailgun document their APIs: `-u sk_test_123:`.
            i += 1
            basic_user = rendered(tokens[i])
        elif token in (
            "-d",
            "--data",
            "--data-raw",
            "--data-binary",
            "--data-urlencode",
            "--json",
        ) and i + 1 < len(tokens):
            json_option = json_option or token == "--json"
            i += 1
            data_indexes.add(i)
            piece = tokens[i]
            if token == "--data-urlencode":
                # Encoded after its expressions are filled in, so a value's "&", "+" or "#"
                # stays inside that value.
                piece = _url_encoded(rendered(piece))
            if data is None:
                data = piece
            else:
                # As curl does: repeated -d values are joined with "&", --json pieces as-is.
                data += ("" if token == "--json" else "&") + piece
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
        for index in range(len(tokens) - 1, -1, -1):
            token = tokens[index]
            if index in data_indexes:
                continue
            candidate = rendered(token)
            if candidate.startswith(("http://", "https://")):
                url = candidate
                break

    for name, value in option_headers.items():
        if not any(k.lower() == name.lower() for k in headers):
            headers[name] = value

    if get_option:
        # curl -G: the data goes into the URL's query string and the request is a GET.
        # Stripe documents its list endpoints as `curl -G URL -d limit=3`.
        if not explicit_method:
            method = "GET"
        if data is not None:
            url += ("&" if "?" in url else "?") + rendered(data)
            data = None

    if head_option and not explicit_method:
        # curl -I: headers only, as a HEAD request.
        method = "HEAD"

    if json_option:
        # curl 7.82+ `--json <data>`: a JSON body, and JSON headers unless the command sets them.
        for name in ("Content-Type", "Accept"):
            if not any(k.lower() == name.lower() for k in headers):
                headers[name] = "application/json"
    if basic_user is not None and not any(k.lower() == "authorization" for k in headers):
        # As curl does: an explicit Authorization header wins, and `-u user` means no password.
        user_pass = basic_user if ":" in basic_user else f"{basic_user}:"
        headers["Authorization"] = "Basic " + base64.b64encode(user_pass.encode()).decode()

    return method, url, headers, data, follow_redirects
