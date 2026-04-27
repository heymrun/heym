"""Resolve the public browser-facing origin for absolute URLs (OAuth redirects, etc.)."""

from starlette.requests import Request

from app.config import settings


def resolve_public_origin(request: Request) -> str:
    """Return the public site origin for OAuth ``redirect_uri`` (Google Sheets OAuth, etc.).

    Uses only the configured ``FRONTEND_URL`` environment variable — never ``Origin`` or
    ``X-Forwarded-*`` headers, which clients can spoof.

    Deployments **must** set ``FRONTEND_URL`` to the URL users open in the browser (scheme + host,
    no trailing slash), e.g. ``https://heym.example.com``, so the callback matches Google Cloud
    redirect URI registration: ``{FRONTEND_URL}/api/credentials/google-sheets/oauth/callback``.

    If ``FRONTEND_URL`` is empty, falls back to ``request.base_url`` (local dev/tests only).
    """
    frontend = (settings.frontend_url or "").strip()
    if frontend:
        return frontend.rstrip("/")

    return str(request.base_url).rstrip("/")
