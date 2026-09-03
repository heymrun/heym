"""Percent-encoding for user-controlled URL path segments.

Integration clients build REST paths by interpolating values a workflow author
or an upstream API supplies (issue keys, repository owners, Grist document IDs).
Interpolating them raw lets a value carrying ``/`` or ``..`` rewrite the request
path: httpx and :func:`urllib.parse.urljoin` both apply RFC 3986 dot-segment
removal, so ``../../`` in an issue key reaches a different endpoint than the
operation intended.

:func:`encode_path_segment` is the one helper for this; do not add a second.
``quote(value, safe="")`` alone is not enough because ``.`` is in the always-safe
set, so a bare ``.`` or ``..`` value survives encoding and is still resolved as a
dot segment.
"""

from __future__ import annotations

from urllib.parse import quote

__all__ = ["encode_path_segment"]


def encode_path_segment(value: object) -> str:
    """Encode one value for safe interpolation into a URL path.

    Every reserved character, ``/`` included, is percent-encoded, and the two
    dot segments are escaped so they cannot be resolved as path navigation.
    """
    segment = quote(str(value), safe="")
    if segment in {".", ".."}:
        return segment.replace(".", "%2E")
    return segment
