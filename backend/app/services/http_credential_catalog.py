"""Credentials the workflow assistant may reference in an http node's curl.

`$credentials.<name>` resolves per credential type (see `get_credentials_context`):
bearer credentials to `Bearer <token>`, header credentials to a whole `Name: value`
line, and API-key credentials to the raw key. The assistant only sees names and
types, so the header line for each one is computed here instead of guessed.
"""

from __future__ import annotations

import json
import keyword
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialType

# Suggested header key per type; None when the credential carries its own header name.
# Google OAuth credentials resolve to a fresh access token, for API calls their node lacks.
_DEFAULT_HEADER_KEYS: dict[CredentialType, str | None] = {
    CredentialType.bearer: "Authorization",
    CredentialType.header: None,
    CredentialType.openai: "Authorization",
    CredentialType.custom: "Authorization",
    CredentialType.cohere: "Authorization",
    CredentialType.google: "x-goog-api-key",
    CredentialType.elevenlabs: "xi-api-key",
    CredentialType.google_sheets: "Authorization",
    CredentialType.google_drive: "Authorization",
}

HTTP_CREDENTIAL_TYPES: frozenset[CredentialType] = frozenset(_DEFAULT_HEADER_KEYS)

_ASK_RULES = (
    "Never pick a credential silently. Before you build an `http` node that needs "
    "authentication, or ask a tool to build one, and at least one credential below fits that "
    "API by name or type (for example a `google_sheets` credential for the Google Sheets API), "
    "emit a `heym-clarify` block with one `single` question per API. Offer only the credentials "
    "that fit that API and never pad the question with unrelated ones. Set "
    '`"prefillLabel": "Header"`, give each fitting credential as '
    '`{"label": "<credential name>", "prefill": "<header key>"}` with the header key that API '
    "documents (start from the suggested key below; leave out `prefill` for credentials that "
    'set their own header name), and end with the plain option `"No credential"`.',
    'The answer comes back as `<credential name> (Header: "<header key>")`. Build that '
    "credential's header line for the returned key with the rules below and send it as "
    "`-H '<header line>'`. If a tool builds the workflow, pass the credential name and header "
    "key in its instructions.",
    "Skip the question when the user already chose the credential in this conversation.",
    'With "No credential", or when nothing below fits, build the request without '
    "authentication and tell the user they can add a Bearer or Header credential and "
    "reference it as `$credentials.<name>`.",
)

_NO_ASK_RULES = (
    "You cannot ask questions in this step. When the request names a credential (and "
    "optionally a header key) for an HTTP call, build its header line with the rules below "
    "and send it as `-H '<header line>'`. When it names none, build the request without "
    "authentication.",
)


def credential_reference(name: str) -> str:
    """Return the expression that resolves a credential by name inside a template."""
    if name.isidentifier() and not keyword.iskeyword(name):
        return f"$credentials.{name}"
    return f"$credentials[{json.dumps(name, ensure_ascii=False)}]"


@dataclass(frozen=True)
class HttpCredential:
    """A credential an http node can send, identified by name and type only."""

    name: str
    type: CredentialType

    @property
    def reference(self) -> str:
        """Expression that resolves this credential's value at run time."""
        return credential_reference(self.name)

    @property
    def header_key(self) -> str | None:
        """Suggested header key, or None when the credential sets its own header name."""
        return _DEFAULT_HEADER_KEYS[self.type]

    def header_line(self, key: str | None = None) -> str:
        """Return the curl header line that sends this credential under `key`."""
        if self.header_key is None:
            return self.reference
        header_key = key or self.header_key
        if self.type != CredentialType.bearer and header_key.lower() == "authorization":
            return f"{header_key}: Bearer {self.reference}"
        return f"{header_key}: {self.reference}"


async def load_http_credentials(db: AsyncSession, user_id: uuid.UUID) -> list[HttpCredential]:
    """Return the user's own credentials an http node can send, without their values."""
    result = await db.execute(
        select(Credential.name, Credential.type)
        .where(
            Credential.owner_id == user_id,
            Credential.type.in_(list(_DEFAULT_HEADER_KEYS)),
        )
        .order_by(Credential.name)
    )
    return [HttpCredential(name, credential_type) for name, credential_type in result.all()]


def _describe(credential: HttpCredential) -> str:
    summary = f"- `{credential.name}` ({credential.type.value}): reference `{credential.reference}`"
    if credential.header_key is None:
        return f"{summary}, header line `{credential.header_line()}` (sets its own header name)"
    return (
        f"{summary}, suggested header key `{credential.header_key}`, "
        f"header line `{credential.header_line()}`"
    )


def format_http_credentials_prompt(credentials: list[HttpCredential], *, interactive: bool) -> str:
    """Return the assistant prompt section for `credentials`, or "" when there are none."""
    if not credentials:
        return ""
    rules = [
        "Prefer a dedicated Heym node. When a node exists for the service and operation "
        "(Slack, GitHub, Linear, Notion, Jira, Google Sheets, Google Drive and the rest), use "
        "it with its `credentialId`. Use the credentials below only for `http` calls that no "
        "node covers.",
        *(_ASK_RULES if interactive else _NO_ASK_RULES),
        "Never write a raw secret, a placeholder key, or a credential name that is not listed "
        "here. Keep existing `$credentials` references when you edit a workflow.",
    ]
    lines = [
        "## Credentials for HTTP requests",
        "",
        "The user has these credentials an `http` node can send. You never see their values; "
        "the node resolves the `$credentials` reference when it runs.",
        "",
        *(f"{index}. {rule}" for index, rule in enumerate(rules, start=1)),
        "",
        "Header line rules:",
        "- `bearer` credentials already start with `Bearer `: `<key>: <reference>`. Never add "
        "another `Bearer `.",
        "- `header` credentials are a whole `Name: value` line: send `<reference>` alone.",
        "- Every other type is a raw API key: `Authorization: Bearer <reference>` when the key "
        "is `Authorization`, otherwise `<key>: <reference>`.",
        "",
        "Available credentials:",
        *(_describe(credential) for credential in credentials),
    ]
    return "\n\n" + "\n".join(lines) + "\n"


async def build_http_credentials_prompt(
    db: AsyncSession, user_id: uuid.UUID, *, interactive: bool
) -> str:
    """Load the user's http credentials and format the assistant prompt section."""
    credentials = await load_http_credentials(db, user_id)
    return format_http_credentials_prompt(credentials, interactive=interactive)
