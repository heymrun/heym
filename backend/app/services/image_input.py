"""Load an image a node was pointed at: a data URL, an http(s) URL or plain base64.

Shared by every node that accepts an image expression, so they agree on which forms
are accepted and on how a caller-controlled URL is fetched.
"""

from __future__ import annotations

import base64
from urllib.parse import urlparse

from app.http_identity import HEYM_USER_AGENT
from app.services.ssrf_guard import get_guarded_http_client, guard_http_url


def load_image_bytes(image_input: str, *, subject: str) -> tuple[bytes, str]:
    """Return the image bytes and their MIME type.

    `subject` names the field in an SSRF refusal, so the user can tell which
    setting pointed at the blocked address.
    """
    if image_input.startswith("data:"):
        header, data = image_input.split(",", 1)
        mime_type = header.split(";")[0].replace("data:", "") or "image/png"
        return base64.b64decode(data), mime_type

    parsed = urlparse(image_input)
    if parsed.scheme in ("http", "https"):
        # The URL can be caller-controlled (e.g. "$userInput.body.imageUrl"), so
        # fetch through the same SSRF guard the HTTP node uses: scheme allowlist,
        # public-IP-only resolution, and dial-time egress pinning.
        guard_http_url(image_input, subject=subject)
        response = get_guarded_http_client().get(
            image_input,
            timeout=30.0,
            headers={"User-Agent": HEYM_USER_AGENT},
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/png")
        mime_type = content_type.split(";")[0] or "image/png"
        return response.content, mime_type

    return base64.b64decode(image_input), "image/png"
