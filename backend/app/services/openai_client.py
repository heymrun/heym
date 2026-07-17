"""OpenAI SDK client construction with Heym's outbound HTTP identity."""

from collections.abc import Mapping
from typing import Any

from openai import OpenAI

from app.http_identity import merge_outbound_headers


def create_openai_client(
    *,
    default_headers: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> OpenAI:
    """Create an OpenAI client that sends Heym's identity on every request."""
    headers = dict(default_headers) if default_headers is not None else None
    return OpenAI(default_headers=merge_outbound_headers(headers), **kwargs)
