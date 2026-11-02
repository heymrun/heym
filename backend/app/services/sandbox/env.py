"""Environment that may cross into a sandbox.

Allowlists fail safe: a new backend secret stays out until someone adds it here.
"""

from __future__ import annotations

import os

CODE_FORWARD_PREFIXES: tuple[str, ...] = (
    "LANG",
    "LANGUAGE",
    "TZ",
    "LC_",
    "SSL_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
SKILL_FORWARD_PREFIXES: tuple[str, ...] = (*CODE_FORWARD_PREFIXES, "NODE_EXTRA_CA_CERTS")


def forwarded_env(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    """``KEY=value`` items for allowlisted variables. HOME never crosses; sandboxes set their own."""
    return tuple(
        f"{key}={value}"
        for key, value in os.environ.items()
        if key != "HOME" and key.startswith(prefixes)
    )
