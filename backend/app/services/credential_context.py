"""What `$credentials.<name>` resolves to for each credential type."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db.models import Credential, CredentialType

logger = logging.getLogger(__name__)

_GOOGLE_OAUTH_TYPES = (CredentialType.google_sheets, CredentialType.google_drive)


def _fresh_google_access_token(credential: Credential, config: dict[str, Any]) -> str:
    """Return the credential's access token, refreshing and persisting it when expired."""
    from app.db.session import SessionLocal
    from app.services.google_drive_service import GoogleDriveService
    from app.services.google_sheets_service import GoogleSheetsService

    service_class = (
        GoogleSheetsService
        if credential.type == CredentialType.google_sheets
        else GoogleDriveService
    )
    try:
        with SessionLocal() as db:
            return service_class(str(credential.id), config, db).access_token()
    except Exception:
        logger.warning("Could not refresh Google credential %s for $credentials", credential.id)
        return ""


async def credential_context_value(credential: Credential, config: dict[str, Any]) -> str | None:
    """Return the value `$credentials.<name>` resolves to, or None to leave it out."""
    if credential.type == CredentialType.bearer:
        token = config.get("bearer_token", "")
        return f"Bearer {token}" if token else ""
    if credential.type == CredentialType.header:
        header_key = config.get("header_key", "")
        header_value = config.get("header_value", "")
        return f"{header_key}: {header_value}" if header_key else header_value
    if credential.type in (CredentialType.discord, CredentialType.slack):
        return config.get("webhook_url", "")
    if credential.type == CredentialType.notion:
        from app.services.notion_service import NotionService

        return NotionService.resolve_bearer_token(config)
    if credential.type == CredentialType.sentry:
        return config.get("api_token", "")
    if credential.type == CredentialType.codex:
        return None
    if credential.type in _GOOGLE_OAUTH_TYPES:
        # Google access tokens expire hourly; the stored one is often stale.
        return await asyncio.to_thread(_fresh_google_access_token, credential, config)
    return config.get("api_key", "")
