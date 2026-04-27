"""Shared HTTP product identity for API responses and outbound requests."""

HEYM_SERVER_AGENT = "heym.run"
HEYM_USER_AGENT = f"Heym (+https://{HEYM_SERVER_AGENT})"


def merge_outbound_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Return default User-Agent merged with optional per-request headers."""
    merged: dict[str, str] = {"User-Agent": HEYM_USER_AGENT}
    if headers:
        merged.update(headers)
    return merged
