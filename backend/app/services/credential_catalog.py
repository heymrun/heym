"""What the workflow assistant may know about the user's credentials.

The assistant sees each owned credential's name, type and id, never its value. This
module holds which credential types each node field accepts, a one-line purpose per
type, how HTTP-capable types are sent as a header, and the prompt section each
assistant surface gets. `$credentials.<name>` resolves per type (see
`credential_context.credential_context_value`): bearer credentials to `Bearer <token>`,
header credentials to a whole `Name: value` line, the other HTTP-capable types to a
raw token.
"""

from __future__ import annotations

import json
import keyword
import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialType


class CredentialPromptMode(str, Enum):
    """How much of the credential flow an assistant surface may run."""

    ASK_AND_CREATE = "ask_and_create"
    APPLY_CHOICES = "apply_choices"
    OFF = "off"


@dataclass(frozen=True)
class CredentialField:
    """A node data field that holds a credential id."""

    name: str
    types: frozenset[CredentialType]
    required: bool = True


def _field(name: str, *types: CredentialType, required: bool = True) -> CredentialField:
    return CredentialField(name, frozenset(types), required)


# Mirrors the per-node `credentialsApi.listByType` calls in the properties panel. `llm` and
# `agent` are left out: they take the model credential the assistant runs on.
NODE_CREDENTIAL_FIELDS: dict[str, tuple[CredentialField, ...]] = {
    "bigquery": (_field("credentialId", CredentialType.bigquery),),
    "clickhouse": (_field("credentialId", CredentialType.clickhouse),),
    "codex": (
        _field("credentialId", CredentialType.codex),
        _field("githubCredentialId", CredentialType.github),
    ),
    "crawler": (_field("credentialId", CredentialType.flaresolverr),),
    "decision": (_field("credentialId", CredentialType.decision),),
    "discord": (_field("credentialId", CredentialType.discord),),
    "discordTrigger": (_field("credentialId", CredentialType.discord_trigger),),
    "github": (_field("credentialId", CredentialType.github),),
    "googleDrive": (_field("credentialId", CredentialType.google_drive),),
    "googleSheets": (_field("credentialId", CredentialType.google_sheets),),
    "grist": (_field("credentialId", CredentialType.grist),),
    "imapTrigger": (_field("credentialId", CredentialType.imap),),
    "jira": (_field("credentialId", CredentialType.jira),),
    "linear": (_field("credentialId", CredentialType.linear),),
    "notion": (_field("credentialId", CredentialType.notion),),
    "opencodeGo": (
        _field("credentialId", CredentialType.opencode),
        _field("githubCredentialId", CredentialType.github),
    ),
    "rabbitmq": (_field("credentialId", CredentialType.rabbitmq),),
    "rag": (_field("rerankerCredentialId", CredentialType.cohere, required=False),),
    "redis": (_field("credentialId", CredentialType.redis),),
    "s3": (_field("credentialId", CredentialType.s3),),
    "sendEmail": (_field("credentialId", CredentialType.smtp),),
    "sentry": (_field("credentialId", CredentialType.sentry),),
    "slack": (_field("credentialId", CredentialType.slack),),
    "slackTrigger": (_field("credentialId", CredentialType.slack_trigger),),
    "supabase": (_field("credentialId", CredentialType.supabase),),
    "telegram": (_field("credentialId", CredentialType.telegram),),
    "telegramTrigger": (_field("credentialId", CredentialType.telegram),),
}

CREDENTIAL_TYPE_PURPOSE: dict[CredentialType, str] = {
    CredentialType.openai: (
        "OpenAI or OpenAI-compatible API key; LLM and Agent nodes, OpenAI API over http"
    ),
    CredentialType.codex: "OpenAI Codex ChatGPT sign-in or access token; Codex node",
    CredentialType.opencode: "OpenCode Go gateway API key; OpenCode Go node",
    CredentialType.google: (
        "Google AI (Gemini) API key; LLM and Agent nodes, Google APIs that take an API key "
        "over http"
    ),
    CredentialType.github: (
        "GitHub personal access token; GitHub, Codex and OpenCode Go nodes, GitHub REST API "
        "over http"
    ),
    CredentialType.jira: (
        "Jira Cloud email and API token, or Data Center username and password; Jira node"
    ),
    CredentialType.linear: "Linear API key or OAuth app; Linear node",
    CredentialType.custom: (
        "OpenAI-compatible endpoint URL and API key; LLM and Agent nodes, that API over http"
    ),
    CredentialType.bearer: "Token for any API that takes `Authorization: Bearer <token>`; http",
    CredentialType.header: (
        "Key for any API that takes it in a custom header such as `X-API-Key`; http"
    ),
    CredentialType.discord: "Discord channel webhook URL; Discord node",
    CredentialType.discord_trigger: "Discord application public key; Discord Trigger node",
    CredentialType.telegram: "Telegram bot token; Telegram and Telegram Trigger nodes",
    CredentialType.slack: "Slack incoming webhook URL; Slack node",
    CredentialType.slack_trigger: "Slack signing secret; Slack Trigger node",
    CredentialType.imap: "IMAP mailbox login; IMAP Trigger node",
    CredentialType.smtp: "SMTP server login; Send Email node",
    CredentialType.redis: "Redis connection; Redis node",
    CredentialType.qdrant: "Qdrant server connection and embedding key; vector stores",
    CredentialType.pgvector: "Embedding key for vectors stored in Heym's Postgres; vector stores",
    CredentialType.grist: "Grist API key and server URL; Grist node",
    CredentialType.rabbitmq: "RabbitMQ connection; RabbitMQ node",
    CredentialType.cohere: "Cohere API key; RAG reranking, Cohere API over http",
    CredentialType.flaresolverr: "FlareSolverr URL; Crawler node",
    CredentialType.google_sheets: (
        "Google OAuth client for Google Sheets; Google Sheets node, Sheets API over http for "
        "operations the node lacks"
    ),
    CredentialType.google_drive: (
        "Google OAuth client for Google Drive; Google Drive node, Drive API over http for "
        "operations the node lacks"
    ),
    CredentialType.bigquery: "Google OAuth client for BigQuery; BigQuery node",
    CredentialType.supabase: "Supabase project URL and key; Supabase node",
    CredentialType.notion: (
        "Notion internal token or OAuth app; Notion node, Notion API over http"
    ),
    CredentialType.sentry: "Sentry auth token; Sentry node, Sentry API over http",
    CredentialType.s3: "AWS access key pair and region; S3 node",
    CredentialType.elevenlabs: "ElevenLabs API key; voice features, ElevenLabs API over http",
    CredentialType.clickhouse: "ClickHouse connection; ClickHouse node",
    CredentialType.rag: "Vector store and embedding settings; vector stores and the RAG node",
    CredentialType.decision: (
        "Decision model endpoint such as TypeSafe Jev; Decision node and Model Router"
    ),
    CredentialType.model_router: (
        "Picks one of the user's LLM credentials per request; LLM and Agent nodes"
    ),
}

# Suggested header key per HTTP-capable type; None when the credential carries its own
# header name. Google OAuth credentials resolve to a fresh access token.
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
    CredentialType.github: "Authorization",
    CredentialType.notion: "Authorization",
    CredentialType.sentry: "Authorization",
}

HTTP_CREDENTIAL_TYPES: frozenset[CredentialType] = frozenset(_DEFAULT_HEADER_KEYS)


def credential_reference(name: str) -> str:
    """Return the expression that resolves a credential by name inside a template."""
    if name.isidentifier() and not keyword.iskeyword(name):
        return f"$credentials.{name}"
    return f"$credentials[{json.dumps(name, ensure_ascii=False)}]"


@dataclass(frozen=True)
class CatalogCredential:
    """An owned credential as the assistant sees it: name, type and id, never a value."""

    id: uuid.UUID
    name: str
    type: CredentialType

    @property
    def reference(self) -> str:
        """Expression that resolves this credential's value at run time."""
        return credential_reference(self.name)

    @property
    def http_capable(self) -> bool:
        """Whether an http node can send this credential in a header."""
        return self.type in HTTP_CREDENTIAL_TYPES

    @property
    def header_key(self) -> str | None:
        """Suggested header key, or None when the credential sets its own header name."""
        return _DEFAULT_HEADER_KEYS.get(self.type)

    def header_line(self, key: str | None = None) -> str:
        """Return the curl header line that sends this credential under `key`."""
        if self.header_key is None:
            return self.reference
        header_key = key or self.header_key
        if self.type != CredentialType.bearer and header_key.lower() == "authorization":
            return f"{header_key}: Bearer {self.reference}"
        return f"{header_key}: {self.reference}"


async def load_credential_catalog(db: AsyncSession, user_id: uuid.UUID) -> list[CatalogCredential]:
    """Return the user's own credentials by id, name and type, never their values."""
    result = await db.execute(
        select(Credential.id, Credential.name, Credential.type)
        .where(Credential.owner_id == user_id)
        .order_by(Credential.name)
    )
    return [
        CatalogCredential(credential_id, name, credential_type)
        for credential_id, name, credential_type in result.all()
    ]


OFF_CREDENTIALS_PROMPT = (
    "\n\n## Credentials\n\n"
    "You cannot use credentials in this step. Build new `http` requests without "
    "authentication, leave credential fields on new nodes empty, and keep every existing "
    "`$credentials` reference and credential id unchanged.\n"
)

_INTRO = (
    "You never see credential values. Below are the user's own credentials by name, type "
    "and id; Heym resolves each value when the workflow runs. This section overrides the "
    "placeholder rule for credential fields: when a credential below fits a node field, put "
    "its id in that field instead of a placeholder."
)

_NODE_RULES = (
    "Prefer a dedicated Heym node. When a node covers the service and operation (see the "
    "node credential fields below), use it and put the credential's id in its credential "
    "field. Use an `http` node only for operations no node covers, and send the credential "
    "with a header line (rules below).",
    "Unless the user asks for a specific model credential, leave `credentialId` on `llm` and "
    "`agent` nodes as a placeholder; Heym fills it with the model this assistant runs on.",
)

_ASK_RULES = (
    "You can open the credential form for the user from a `heym-clarify` card; the user fills "
    "it in and you never see the values. When the user asks to create, add or connect a "
    "credential, never send them to the Credentials tab: emit a `heym-clarify` block with one "
    "`single` question that offers a create option (below) for each fitting type, usually "
    "one, and a cancel option, then stop.",
    "When the user asks to update, edit, rename, rotate, reconnect or re-authorize one of "
    "their credentials, emit a `heym-clarify` block with one `single` question that offers "
    '`{"label": "<short text in the user\'s language>", "edit": {"id": "<credential id>"}}` '
    "for each listed credential that matches by name or type, and a cancel option. The form "
    "opens with that credential loaded and its secrets masked. The answer comes back as "
    '`Updated credential "<name>" (<type>)`. When no listed credential matches, say so and '
    "offer a create option instead.",
    "Never pick a credential silently. Before you build a node with a required credential "
    "field, or an `http` call that needs authentication, emit a `heym-clarify` block with one "
    "`single` question per service and stop.",
    "When the user owns credentials of a fitting type, offer each of them, then a create "
    "option, then an option to continue without a credential. Offer only the credentials "
    "that fit that API and never pad the question with unrelated ones. For `http`, give each "
    'credential as `{"label": "<credential name>", "prefill": "<header key>"}` with '
    '`"prefillLabel": "Header"`; leave out `prefill` for credentials that set their own '
    "header name.",
    "When the user owns none, ask whether to create one, with the create option and an "
    "option to continue without a credential.",
    'The create option is `{"label": "<short text in the user\'s language>", "create": '
    '{"type": "<credential type>", "name": "<suggested name>"}}`. Use the node field\'s '
    "credential type. For `http`, use the service's own HTTP-capable type when it has one "
    "(for example `google_sheets`), otherwise `bearer` for `Authorization: Bearer` APIs or "
    "`header` for a key in a custom header. The suggested name must differ from every "
    "credential name listed here. Credential questions are never optional.",
    'Answers come back as `<name>`, `<name> (Header: "<header key>")`, '
    '`Created credential "<name>" (<type>)`, or your continue-without label. A created '
    "credential appears in this list on the next turn with its id; use it without asking "
    "again, and for `http` use its suggested header key.",
    "Do not ask again about a service already answered in this conversation, or about a "
    "node you are editing that already has a credential.",
    "When the user continues without a credential, leave the field empty or send the "
    "request without authentication, and tell the user they can add the credential later.",
    "If a tool builds or edits the workflow, pass every answer in its `credential_choices` "
    'argument: `{"credential_type": "<type>", "credential_name": "<name>"}`, an empty '
    "`credential_name` for continue-without, and `header_key` for `http`. If the tool "
    "returns `requires_credentials`, ask about each listed need the same way, then call the "
    "tool again with `credential_choices`.",
)

_APPLY_RULES = (
    "You cannot ask questions in this step. The request lists the credential choices the "
    "user made. For each node field or `http` call a choice covers, use the named "
    "credential: put its id in the node's credential field, or send its header line under "
    "the chosen header key. When a choice has no credential name, leave that field empty or "
    "send the request without authentication. When no choice covers a service, leave its "
    "credential field empty.",
)

_SAFETY_RULE = (
    "Never write a raw secret, a placeholder key, or a credential name that is not listed "
    "here. Keep existing `$credentials` references and credential ids when you edit a "
    "workflow."
)

_HEADER_RULES = (
    "Header line rules for `http`:",
    "- `bearer` credentials already start with `Bearer `: `<key>: <reference>`. Never add "
    "another `Bearer `.",
    "- `header` credentials are a whole `Name: value` line: send `<reference>` alone.",
    "- Every other HTTP-capable type is a raw token: `Authorization: Bearer <reference>` when "
    "the key is `Authorization`, otherwise `<key>: <reference>`.",
)


def _node_field_lines() -> list[str]:
    lines: list[str] = []
    for node_type, fields in NODE_CREDENTIAL_FIELDS.items():
        parts: list[str] = []
        for spec in fields:
            types = " or ".join(sorted(t.value for t in spec.types))
            optional = ", optional" if not spec.required else ""
            parts.append(f"`{spec.name}` ({types}{optional})")
        lines.append(f"- `{node_type}`: " + ", ".join(parts))
    return lines


def _describe(credential: CatalogCredential) -> str:
    summary = f"- `{credential.name}` ({credential.type.value}), id `{credential.id}`"
    if not credential.http_capable:
        return summary
    if credential.header_key is None:
        return (
            f"{summary}, http header line `{credential.header_line()}` (sets its own header name)"
        )
    return (
        f"{summary}, http reference `{credential.reference}`, suggested header key "
        f"`{credential.header_key}`, header line `{credential.header_line()}`"
    )


def format_credentials_prompt(
    credentials: list[CatalogCredential], mode: CredentialPromptMode
) -> str:
    """Return the assistant prompt section for `mode`."""
    if mode is CredentialPromptMode.OFF:
        return OFF_CREDENTIALS_PROMPT
    mode_rules = _ASK_RULES if mode is CredentialPromptMode.ASK_AND_CREATE else _APPLY_RULES
    rules = [*_NODE_RULES, *mode_rules, _SAFETY_RULE]
    http_types = ", ".join(
        f"`{t.value}`" for t in sorted(HTTP_CREDENTIAL_TYPES, key=lambda t: t.value)
    )
    lines = [
        "## Credentials",
        "",
        _INTRO,
        "",
        *(f"{index}. {rule}" for index, rule in enumerate(rules, start=1)),
        "",
        *_HEADER_RULES,
        "",
        "Node credential fields:",
        *_node_field_lines(),
        "",
        "Credential types:",
        *(f"- `{t.value}`: {purpose}" for t, purpose in CREDENTIAL_TYPE_PURPOSE.items()),
        "",
        f"HTTP-capable types: {http_types}",
        "",
        "The user's credentials:",
        *([_describe(c) for c in credentials] or ["- The user has no credentials yet."]),
    ]
    return "\n\n" + "\n".join(lines) + "\n"


async def build_credentials_prompt(
    db: AsyncSession, user_id: uuid.UUID, mode: CredentialPromptMode
) -> str:
    """Load the user's credentials and format the prompt section for `mode`."""
    if mode is CredentialPromptMode.OFF:
        return OFF_CREDENTIALS_PROMPT
    return format_credentials_prompt(await load_credential_catalog(db, user_id), mode)
