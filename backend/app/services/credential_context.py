"""What `$credentials.<name>` resolves to for each credential type."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

from app.db.models import Credential, CredentialType

logger = logging.getLogger(__name__)


class CredentialsContext(dict[str, str]):
    """`$credentials` values, plus the Secret-backed ones this process can't serve yet.

    A missing `$credentials.x` resolves to nothing rather than failing, so a run would
    carry on with an empty value. `unavailable` lets the run entry points fail it up
    front instead, before any node has had side effects, with the reason.
    """

    def __init__(self, *args: Any, unavailable: dict[str, str] | None = None) -> None:
        super().__init__(*args)
        self.unavailable: dict[str, str] = dict(unavailable or {})


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def unavailable_credential_error(
    credentials_context: dict[str, str] | None,
    nodes: list[dict],
    workflow_cache: dict[str, dict] | None = None,
) -> str | None:
    """Why this run can't start, when it references a credential this process can't serve.

    Looks through the workflow's nodes and the sub-workflows it calls. Nodes that
    pick a credential by id need no check here: reading it raises with the same reason.
    """
    unavailable = getattr(credentials_context, "unavailable", None)
    if not unavailable:
        return None
    texts = list(_strings([nodes, list((workflow_cache or {}).values())]))
    for name, reason in unavailable.items():
        forms = (f"credentials.{name}", f'credentials["{name}"]', f"credentials['{name}']")
        if any(form in text for text in texts for form in forms):
            return f'credential "{name}": {reason}'
    return None


_GOOGLE_OAUTH_TYPES = (
    CredentialType.google_sheets,
    CredentialType.google_drive,
    CredentialType.google_meet,
)


def _fresh_google_access_token(credential: Credential, config: dict[str, Any]) -> str:
    """Return the credential's access token, refreshing and persisting it when expired."""
    from app.db.session import SessionLocal
    from app.services.google_drive_service import GoogleDriveService
    from app.services.google_meet_service import GoogleMeetService
    from app.services.google_sheets_service import GoogleSheetsService

    service_class = {
        CredentialType.google_sheets: GoogleSheetsService,
        CredentialType.google_drive: GoogleDriveService,
        CredentialType.google_meet: GoogleMeetService,
    }[credential.type]
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
    if credential.type == CredentialType.slack_bot:
        return config.get("bot_token", "")
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


def mask_credentials_context(credentials_context: dict[str, str] | None) -> dict[str, str]:
    """Return a preview-safe credentials context with secret values masked."""
    if not credentials_context:
        return {}

    masked_context: dict[str, str] = {}
    for name, value in credentials_context.items():
        if not value:
            masked_context[name] = value
        elif len(value) > 7:
            masked_context[name] = value[:7] + "**"
        else:
            masked_context[name] = "**"
    return masked_context


def refused_run_result(
    workflow_id: Any,
    credentials_context: dict[str, str] | None,
    nodes: list[dict],
    workflow_cache: dict[str, dict] | None,
) -> Any:
    """A failed ExecutionResult for a run that can't start, or None to let it run.

    Returned before any node runs, so a run that couldn't finish has no side effects.
    """
    error = unavailable_credential_error(credentials_context, nodes, workflow_cache)
    if error is None:
        return None
    from app.services.workflow_executor import ExecutionResult

    return ExecutionResult(
        workflow_id=workflow_id, status="error", outputs={"error": error}, execution_time_ms=0.0
    )


def refused_run_event(
    workflow_id: Any,
    credentials_context: dict[str, str] | None,
    nodes: list[dict],
    workflow_cache: dict[str, dict] | None,
) -> dict[str, Any] | None:
    """The streaming form of `refused_run_result`: one final `execution_complete` event."""
    error = unavailable_credential_error(credentials_context, nodes, workflow_cache)
    if error is None:
        return None
    return {
        "type": "execution_complete",
        "workflow_id": str(workflow_id),
        "status": "error",
        "outputs": {"error": error},
        "execution_time_ms": 0.0,
        "node_results": [],
        "sub_workflow_executions": [],
    }
