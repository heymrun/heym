"""OpenAI SDK client construction with Heym's outbound HTTP identity."""

import uuid
from collections.abc import Mapping
from typing import Any

from openai import DEFAULT_CONNECTION_LIMITS, DEFAULT_TIMEOUT, OpenAI

from app.http_identity import merge_outbound_headers
from app.services.opencode_catalog import is_opencode_base_url
from app.services.ssrf_guard import build_guarded_http_client, guard_http_url


def create_openai_client(
    *,
    default_headers: Mapping[str, str] | None = None,
    session_id: str | None = None,
    **kwargs: Any,
) -> OpenAI:
    """Send Heym's identity and an OpenCode session ID scoped to this conversation."""
    headers = dict(default_headers or {})
    if is_opencode_base_url(kwargs.get("base_url")):
        existing_session = None
        for name in list(headers):
            if name.lower() == "x-opencode-session":
                existing_session = headers.pop(name)
        headers["x-opencode-session"] = (
            (session_id or "").strip() or (existing_session or "").strip() or str(uuid.uuid4())
        )
    return OpenAI(default_headers=merge_outbound_headers(headers), **kwargs)


def create_guarded_openai_client(
    *,
    base_url: str,
    subject: str,
    default_headers: Mapping[str, str] | None = None,
    session_id: str | None = None,
    **kwargs: Any,
) -> OpenAI:
    """Create an OpenAI-compatible client for a credential-controlled endpoint."""
    if "http_client" in kwargs:
        raise ValueError("Guarded OpenAI clients manage their own HTTP transport")

    guard_http_url(base_url, subject)
    http_client = build_guarded_http_client(
        timeout=DEFAULT_TIMEOUT,
        limits=DEFAULT_CONNECTION_LIMITS,
        follow_redirects=True,
    )
    try:
        return create_openai_client(
            base_url=base_url,
            default_headers=default_headers,
            session_id=session_id,
            http_client=http_client,
            **kwargs,
        )
    except Exception:
        http_client.close()
        raise
