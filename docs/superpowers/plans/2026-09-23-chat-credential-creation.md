# Chat Credential Selection and Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a workflow the assistant builds needs a credential, the canvas builder, the Chat tab (including its `create_workflow` / `edit_workflow` tools) and Docs chat ask which one to use, offer to create one in the existing credential dialog, and wire the result in. The model only ever sees names, types and ids. `heym_chat` over MCP never acts on credentials.

**Architecture:** A backend credential catalog (`credential_catalog.py`) replaces the HTTP-only catalog and renders one of three prompt modes per surface. A pure pass (`generated_credentials.py`) makes chat-built workflows deterministic: names become ids, foreign ids are dropped, the user's `credential_choices` fill empty fields, and an undecided new node returns `requires_credentials` instead of saving. The frontend extends the `heym-clarify` protocol with a `create` option (opens `CredentialDialog` through `CredentialCreateButton`) and `optional` questions. The dialog's five OAuth flows move to one `useOAuthPopup` composable that also shows the authorization link and polls for completion.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, pytest (`unittest` style, `AsyncMock`); Vue 3 `<script setup>`, TypeScript strict, Vitest for pure logic only.

**Spec:** `docs/superpowers/specs/2026-09-23-chat-credential-creation-design.md`

---

## Ground rules for this repository

- **Do not commit, branch or push.** The user keeps heymrun work as a local diff. Every task ends with a verification checkpoint instead of a commit.
- **Backend test environment.** The tracked `.env` enables OTel against a collector that does not run locally, which hangs pytest. Run every backend command from `backend/` after:
  ```bash
  export HEYM_OTEL_ENABLED=false HEYM_HTTP_ALLOW_PRIVATE_URLS=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes
  ```
- **Frontend tests.** Only pure-logic Vitest specs (`src/utils/*.test.ts`, existing `src/components/Docs/*.test.ts`). No new component, UI or E2E tests. Verify components with `bun run lint` and `bun run typecheck` from `frontend/`.
- **No Turkish text** in code, comments or docs.
- **Vue templates** put one attribute per line when an element has more than one.
- **Import order.** Python: stdlib, third-party, internal (Ruff sorts). TypeScript: Vue, external libraries, internal types, internal code.

## File structure

**Backend**
- Create `backend/app/services/credential_catalog.py`: prompt modes, the node → credential field map, one purpose per credential type, HTTP header rules, the owned-credential loader and the prompt section per mode. Replaces `http_credential_catalog.py` (deleted in Task 4).
- Create `backend/app/services/generated_credentials.py`: `credential_choices` parsing and the deterministic credential pass over generated nodes, plus the `requires_credentials` and MCP payloads.
- Modify `backend/app/services/workflow_dsl_prompt.py`: `CLARIFY_PROTOCOL_PROMPT` documents `create` options, `optional` questions and `(skipped)`; `build_assistant_prompt(http_credentials_prompt=)` becomes `credentials_prompt=`.
- Modify `backend/app/api/ai_assistant.py`: imports, tool schemas, create/edit tools, `stream_dashboard_chat(credential_mode=)`, the canvas and Docs chat endpoints, tool summaries.
- Modify `backend/app/api/chats.py`: `ChatTurn.credential_mode`, `SystemPromptParts.credentials_block`, prompt assembly, MCP turns run `OFF`.
- Tests: create `tests/test_credential_catalog.py`, `tests/test_generated_credentials.py`, `tests/test_chat_credential_mode.py`, `tests/test_advisory_credential_catalog_no_values.py`; delete `tests/test_http_credential_catalog.py`; update `tests/test_dashboard_chat_api.py`, `tests/test_workflow_assistant_stream.py`, `tests/test_clarify_protocol_prompt.py`.

**Frontend**
- Modify `frontend/src/types/clarify.ts`, `frontend/src/utils/parseClarify.ts`, `frontend/src/utils/parseClarify.test.ts`.
- Create `frontend/src/components/Credentials/useOAuthPopup.ts` and `frontend/src/components/Credentials/OAuthAuthorizeLink.vue`.
- Modify `frontend/src/components/Credentials/CredentialDialog.vue`.
- Create `frontend/src/components/Credentials/CredentialCreateButton.vue`.
- Modify `frontend/src/components/ui/ClarifyCard.vue`.
- Create `frontend/src/utils/generatedCredentialFields.ts` and its `.test.ts`; modify `frontend/src/components/Panels/DebugPanel.vue`.
- Modify `frontend/src/components/Docs/useDocsChatDialog.ts` and `frontend/src/components/Docs/DocsChatDialog.vue`.
- Release tour: modify `releaseRegistry.ts`, `tourVisuals.ts`, `releaseTourMapper.test.ts`; create `components/visuals/ChatCredentialsTourVisual.vue`; delete `components/visuals/ClusterInstancesTourVisual.vue` (all under `frontend/src/features/release-tour/`).
- Docs under `frontend/src/docs/content/`.

---

## Task 1: Credential catalog module

**Files:**
- Create: `backend/app/services/credential_catalog.py`
- Create: `backend/tests/test_credential_catalog.py`

The old `http_credential_catalog.py` stays in place until Task 4 so `ai_assistant.py` keeps importing.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_credential_catalog.py`:

```python
"""The credential catalog the workflow assistant sees: never a value, only names and types."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.credential_catalog import (
    CREDENTIAL_TYPE_PURPOSE,
    HTTP_CREDENTIAL_TYPES,
    NODE_CREDENTIAL_FIELDS,
    OFF_CREDENTIALS_PROMPT,
    CatalogCredential,
    CredentialPromptMode,
    build_credentials_prompt,
    credential_reference,
    format_credentials_prompt,
    load_credential_catalog,
)
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.node_execution.registry import handler_module_names
from app.services.workflow_executor import WorkflowExecutor

ASK = CredentialPromptMode.ASK_AND_CREATE
APPLY = CredentialPromptMode.APPLY_CHOICES
OFF = CredentialPromptMode.OFF


def _cred(name: str, credential_type: CredentialType) -> CatalogCredential:
    return CatalogCredential(uuid.uuid4(), name, credential_type)


def _sent_headers(header_line: str, credentials: dict[str, str]) -> httpx.Headers:
    """Send one header line through a real http node and return the request headers."""
    received: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    context = NodeExecutionContext(
        executor=WorkflowExecutor(nodes=[], edges=[], credentials_context=credentials),
        node_id="http1",
        inputs={},
        allow_branch_skip=True,
        start_time=0.0,
        node={},
        node_type="http",
        node_data={"curl": f"curl -X GET https://api.example.com -H '{header_line}'"},
        node_label="request",
    )
    with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
        ):
            http_node.execute(context)
    return received[0].headers


class CredentialReferenceTests(unittest.TestCase):
    def test_identifier_name_uses_dot_access(self) -> None:
        self.assertEqual(credential_reference("google"), "$credentials.google")

    def test_hyphenated_name_uses_subscript(self) -> None:
        """`$credentials.slack-general-crazy` stops resolving at the first hyphen."""
        self.assertEqual(
            credential_reference("slack-general-crazy"),
            '$credentials["slack-general-crazy"]',
        )

    def test_python_keyword_name_uses_subscript(self) -> None:
        self.assertEqual(credential_reference("class"), '$credentials["class"]')

    def test_leading_digit_name_uses_subscript(self) -> None:
        self.assertEqual(credential_reference("1password"), '$credentials["1password"]')


class HeaderLineTests(unittest.TestCase):
    def test_bearer_credential_is_not_prefixed_twice(self) -> None:
        credential = _cred("perplexity", CredentialType.bearer)

        self.assertEqual(credential.header_line(), "Authorization: $credentials.perplexity")

    def test_header_credential_is_sent_as_the_whole_line(self) -> None:
        credential = _cred("burak31", CredentialType.header)

        self.assertIsNone(credential.header_key)
        self.assertEqual(credential.header_line(), "$credentials.burak31")

    def test_api_key_under_authorization_gets_bearer_prefix(self) -> None:
        credential = _cred("openai", CredentialType.openai)

        self.assertEqual(credential.header_line(), "Authorization: Bearer $credentials.openai")

    def test_google_defaults_to_goog_api_key_header(self) -> None:
        credential = _cred("google", CredentialType.google)

        self.assertEqual(credential.header_line(), "x-goog-api-key: $credentials.google")

    def test_chosen_key_replaces_the_default(self) -> None:
        google = _cred("google", CredentialType.google)
        openai = _cred("openai", CredentialType.openai)

        self.assertEqual(
            google.header_line("Authorization"), "Authorization: Bearer $credentials.google"
        )
        self.assertEqual(openai.header_line("api-key"), "api-key: $credentials.openai")

    def test_header_lines_authenticate_through_the_http_node(self) -> None:
        """Each line resolves to the header the API expects, using real resolved values."""
        credentials = {
            "perplexity": "Bearer pplx-token-123",
            "vendor": "X-Api-Key: vendor-secret-456",
            "openai": "sk-openai-789",
            "google": "AIzaSyExample000",
            "voice": "eleven-key-111",
            "slack-general-crazy": "Bearer hyphen-token-222",
            "sheet": "ya29.fresh-token",
            "gh": "ghp_token_333",
            "wiki": "secret_notion_444",
            "errors": "sntrys_token_555",
        }
        cases = [
            (_cred("perplexity", CredentialType.bearer), "authorization", "Bearer pplx-token-123"),
            (_cred("vendor", CredentialType.header), "x-api-key", "vendor-secret-456"),
            (_cred("openai", CredentialType.openai), "authorization", "Bearer sk-openai-789"),
            (_cred("google", CredentialType.google), "x-goog-api-key", "AIzaSyExample000"),
            (_cred("voice", CredentialType.elevenlabs), "xi-api-key", "eleven-key-111"),
            (
                _cred("slack-general-crazy", CredentialType.bearer),
                "authorization",
                "Bearer hyphen-token-222",
            ),
            (
                _cred("sheet", CredentialType.google_sheets),
                "authorization",
                "Bearer ya29.fresh-token",
            ),
            (_cred("gh", CredentialType.github), "authorization", "Bearer ghp_token_333"),
            (_cred("wiki", CredentialType.notion), "authorization", "Bearer secret_notion_444"),
            (_cred("errors", CredentialType.sentry), "authorization", "Bearer sntrys_token_555"),
        ]
        for credential, header, expected in cases:
            with self.subTest(credential=credential.name):
                headers = _sent_headers(credential.header_line(), credentials)

                self.assertEqual(headers.get(header), expected)


class HttpScopeTests(unittest.TestCase):
    def test_credentials_usable_in_a_header_are_http_capable(self) -> None:
        for credential_type in (
            CredentialType.bearer,
            CredentialType.header,
            CredentialType.openai,
            CredentialType.google,
            CredentialType.custom,
            CredentialType.cohere,
            CredentialType.elevenlabs,
            CredentialType.google_sheets,
            CredentialType.google_drive,
            CredentialType.github,
            CredentialType.notion,
            CredentialType.sentry,
        ):
            with self.subTest(credential_type=credential_type):
                self.assertIn(credential_type, HTTP_CREDENTIAL_TYPES)

    def test_types_without_a_usable_header_value_are_left_out(self) -> None:
        """Connection, webhook, Basic-auth and mixed-shape credentials stay node-only."""
        for credential_type in (
            CredentialType.bigquery,
            CredentialType.smtp,
            CredentialType.redis,
            CredentialType.slack,
            CredentialType.codex,
            CredentialType.model_router,
            CredentialType.jira,
            CredentialType.linear,
        ):
            with self.subTest(credential_type=credential_type):
                self.assertNotIn(credential_type, HTTP_CREDENTIAL_TYPES)
                self.assertFalse(_cred("x", credential_type).http_capable)


class NodeCredentialFieldTests(unittest.TestCase):
    def test_every_mapped_node_type_is_registered(self) -> None:
        unknown = sorted(set(NODE_CREDENTIAL_FIELDS) - set(handler_module_names()))
        self.assertEqual(unknown, [], f"NODE_CREDENTIAL_FIELDS names unknown nodes: {unknown}")

    def test_accepted_types_are_credential_types(self) -> None:
        for node_type, fields in NODE_CREDENTIAL_FIELDS.items():
            for spec in fields:
                with self.subTest(node_type=node_type, field=spec.name):
                    self.assertTrue(spec.types)
                    self.assertTrue(all(isinstance(t, CredentialType) for t in spec.types))

    def test_coding_agents_also_need_a_github_credential(self) -> None:
        for node_type, credential_type in (
            ("codex", CredentialType.codex),
            ("opencodeGo", CredentialType.opencode),
        ):
            with self.subTest(node_type=node_type):
                fields = {spec.name: spec for spec in NODE_CREDENTIAL_FIELDS[node_type]}
                self.assertEqual(fields["credentialId"].types, frozenset({credential_type}))
                self.assertEqual(
                    fields["githubCredentialId"].types, frozenset({CredentialType.github})
                )

    def test_rag_reranker_is_optional(self) -> None:
        (reranker,) = NODE_CREDENTIAL_FIELDS["rag"]
        self.assertEqual(reranker.name, "rerankerCredentialId")
        self.assertFalse(reranker.required)

    def test_llm_nodes_are_left_to_the_selected_model_credential(self) -> None:
        self.assertNotIn("llm", NODE_CREDENTIAL_FIELDS)
        self.assertNotIn("agent", NODE_CREDENTIAL_FIELDS)


class CredentialTypePurposeTests(unittest.TestCase):
    def test_every_credential_type_has_a_purpose(self) -> None:
        missing = sorted(t.value for t in set(CredentialType) - set(CREDENTIAL_TYPE_PURPOSE))
        self.assertEqual(
            missing,
            [],
            "Credential types with no entry in CREDENTIAL_TYPE_PURPOSE: "
            f"{missing}. Add a one-line purpose in app/services/credential_catalog.py.",
        )


class LoadCredentialCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_owned_credentials_by_id_name_and_type_only(self) -> None:
        user_id = uuid.uuid4()
        google_id = uuid.uuid4()
        slack_id = uuid.uuid4()
        result = MagicMock()
        result.all.return_value = [
            (google_id, "google", CredentialType.google),
            (slack_id, "slack-main", CredentialType.slack),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        credentials = await load_credential_catalog(db, user_id)

        self.assertEqual(
            credentials,
            [
                CatalogCredential(google_id, "google", CredentialType.google),
                CatalogCredential(slack_id, "slack-main", CredentialType.slack),
            ],
        )
        statement = db.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("credentials.owner_id", sql)
        self.assertNotIn("encrypted_config", sql)
        self.assertIn(user_id, statement.compile().params.values())

    async def test_ask_prompt_is_built_even_without_credentials(self) -> None:
        """Creation matters most when the user owns nothing yet."""
        result = MagicMock()
        result.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        prompt = await build_credentials_prompt(db, uuid.uuid4(), ASK)

        self.assertIn("The user has no credentials yet.", prompt)
        self.assertIn('"create"', prompt)

    async def test_off_prompt_does_not_query_credentials(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()

        prompt = await build_credentials_prompt(db, uuid.uuid4(), OFF)

        self.assertEqual(prompt, OFF_CREDENTIALS_PROMPT)
        db.execute.assert_not_awaited()


class CredentialsPromptTests(unittest.TestCase):
    credentials = [
        _cred("google", CredentialType.google),
        _cred("burak31", CredentialType.header),
        _cred("slack-general-crazy", CredentialType.bearer),
        _cred("github-work", CredentialType.github),
        _cred("smtp-main", CredentialType.smtp),
    ]

    def test_lists_every_credential_with_its_id(self) -> None:
        prompt = format_credentials_prompt(self.credentials, ASK)

        for credential in self.credentials:
            with self.subTest(credential=credential.name):
                self.assertIn(
                    f"`{credential.name}` ({credential.type.value}), id `{credential.id}`", prompt
                )

    def test_http_capable_credentials_carry_reference_and_header_line(self) -> None:
        prompt = format_credentials_prompt(self.credentials, ASK)

        self.assertIn("`$credentials.google`", prompt)
        self.assertIn("`x-goog-api-key: $credentials.google`", prompt)
        self.assertIn("`$credentials.burak31`", prompt)
        self.assertIn('`Authorization: $credentials["slack-general-crazy"]`', prompt)
        self.assertIn('`Authorization: Bearer $credentials["github-work"]`', prompt)
        self.assertNotIn('$credentials["smtp-main"]', prompt)

    def test_ask_prompt_asks_offers_creation_and_hands_answers_to_tools(self) -> None:
        prompt = format_credentials_prompt(self.credentials, ASK)

        self.assertIn("heym-clarify", prompt)
        self.assertIn('"prefillLabel": "Header"', prompt)
        self.assertIn('"create"', prompt)
        self.assertIn('Created credential "<name>" (<type>)', prompt)
        self.assertIn("credential_choices", prompt)
        self.assertIn("requires_credentials", prompt)
        self.assertIn("dedicated Heym node", prompt)
        self.assertIn("Credential questions are never optional", prompt)

    def test_ask_prompt_offers_only_credentials_that_fit_the_api(self) -> None:
        prompt = format_credentials_prompt(self.credentials, ASK)

        self.assertIn("Offer only the credentials that fit that API", prompt)
        self.assertIn("never pad the question with unrelated ones", prompt)

    def test_apply_prompt_uses_the_choices_without_asking(self) -> None:
        prompt = format_credentials_prompt(self.credentials, APPLY)

        self.assertIn("cannot ask", prompt)
        self.assertIn("dedicated Heym node", prompt)
        self.assertNotIn("heym-clarify", prompt)
        self.assertNotIn('"prefillLabel"', prompt)

    def test_off_prompt_names_no_credential_and_keeps_existing_references(self) -> None:
        prompt = format_credentials_prompt(self.credentials, OFF)

        self.assertEqual(prompt, OFF_CREDENTIALS_PROMPT)
        self.assertIn("without authentication", prompt)
        self.assertIn("keep every existing `$credentials` reference", prompt)
        for credential in self.credentials:
            self.assertNotIn(credential.name, prompt)

    def test_prompt_lists_node_fields_and_type_purposes(self) -> None:
        prompt = format_credentials_prompt([], ASK)

        self.assertIn("- `github`: `credentialId` (github)", prompt)
        self.assertIn("`githubCredentialId` (github)", prompt)
        self.assertIn("`rerankerCredentialId` (cohere, optional)", prompt)
        purpose = CREDENTIAL_TYPE_PURPOSE[CredentialType.google_sheets]
        self.assertIn(f"- `google_sheets`: {purpose}", prompt)

    def test_prompt_keeps_llm_credentials_with_heym(self) -> None:
        prompt = format_credentials_prompt(self.credentials, ASK)

        self.assertIn("`llm` and `agent` nodes", prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_credential_catalog.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.credential_catalog'`.

- [ ] **Step 3: Create the module**

Create `backend/app/services/credential_catalog.py`:

```python
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
    CredentialType.notion: "Notion internal token or OAuth app; Notion node, Notion API over http",
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


async def load_credential_catalog(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CatalogCredential]:
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
            f"{summary}, http header line `{credential.header_line()}` "
            "(sets its own header name)"
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_credential_catalog.py -q`
Expected: all pass.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check app/services/credential_catalog.py tests/test_credential_catalog.py && uv run ruff format app/services/credential_catalog.py tests/test_credential_catalog.py`
Expected: clean. If Ruff reports E501 on a purpose string, split it with implicit concatenation as the other entries do.

---

## Task 2: Deterministic credential pass for generated workflows

**Files:**
- Create: `backend/app/services/generated_credentials.py`
- Create: `backend/tests/test_generated_credentials.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_generated_credentials.py`:

```python
"""Credential handling for workflows the chat builder generates."""

import unittest
import uuid
from typing import Any

from app.db.models import CredentialType
from app.services.credential_catalog import CatalogCredential, CredentialPromptMode
from app.services.generated_credentials import (
    CredentialChoice,
    CredentialNeed,
    CredentialPassResult,
    apply_generated_credentials,
    credentials_to_assign_payload,
    format_credential_choices,
    parse_credential_choices,
    requires_credentials_payload,
)

GITHUB_WORK = CatalogCredential(uuid.uuid4(), "github-work", CredentialType.github)
GITHUB_OTHER = CatalogCredential(uuid.uuid4(), "github-other", CredentialType.github)
SLACK_MAIN = CatalogCredential(uuid.uuid4(), "slack-main", CredentialType.slack)
CODEX_MAIN = CatalogCredential(uuid.uuid4(), "codex-main", CredentialType.codex)
CATALOG = [GITHUB_WORK, GITHUB_OTHER, SLACK_MAIN, CODEX_MAIN]
APPLY = CredentialPromptMode.APPLY_CHOICES
OFF = CredentialPromptMode.OFF


def _node(
    node_type: str,
    credential_id: str | None = None,
    *,
    node_id: str = "n1",
    label: str = "fetchRepos",
) -> dict[str, Any]:
    data: dict[str, Any] = {"label": label}
    if credential_id is not None:
        data["credentialId"] = credential_id
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _run(
    nodes: list[dict[str, Any]],
    *,
    choices: list[CredentialChoice] | None = None,
    previous: list[dict[str, Any]] | None = None,
    mode: CredentialPromptMode = APPLY,
) -> CredentialPassResult:
    return apply_generated_credentials(
        nodes, catalog=CATALOG, choices=choices or [], previous_nodes=previous, mode=mode
    )


def _github_need(node: str = "fetchRepos") -> CredentialNeed:
    return CredentialNeed(
        node=node,
        node_type="github",
        field="credentialId",
        credential_types=("github",),
        existing=("github-other", "github-work"),
    )


class ResolveTests(unittest.TestCase):
    def test_owned_id_of_the_right_type_is_kept(self) -> None:
        result = _run([_node("github", str(GITHUB_WORK.id))])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))
        self.assertEqual(result.needs, [])

    def test_uppercase_id_is_normalized(self) -> None:
        result = _run([_node("github", str(GITHUB_WORK.id).upper())])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_exact_credential_name_is_rewritten_to_its_id(self) -> None:
        result = _run([_node("github", "github-work")])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_unowned_id_is_cleared_and_reported(self) -> None:
        result = _run([_node("github", str(uuid.uuid4()))])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
        self.assertEqual(result.needs, [_github_need()])

    def test_wrong_type_id_is_cleared(self) -> None:
        result = _run([_node("github", str(SLACK_MAIN.id))])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")

    def test_placeholder_is_cleared(self) -> None:
        result = _run([_node("github", "YOUR_CREDENTIAL_ID")])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")

    def test_input_nodes_are_not_mutated(self) -> None:
        nodes = [_node("github", "github-work")]

        _run(nodes)

        self.assertEqual(nodes[0]["data"]["credentialId"], "github-work")

    def test_nodes_without_credential_fields_pass_through(self) -> None:
        nodes = [_node("textInput"), _node("llm", "YOUR_CREDENTIAL_ID", node_id="n2")]

        result = _run(nodes)

        self.assertEqual(result.nodes, nodes)
        self.assertEqual(result.needs, [])


class ChoiceTests(unittest.TestCase):
    def test_choice_fills_an_empty_required_field(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "github-work")]

        result = _run([_node("github", "")], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))
        self.assertEqual(result.needs, [])

    def test_single_choice_wins_over_a_different_credential_on_a_new_node(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "github-work")]

        result = _run([_node("github", str(GITHUB_OTHER.id))], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_choice_naming_a_missing_credential_is_still_a_need(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "does-not-exist")]

        result = _run([_node("github", "")], choices=choices)

        self.assertEqual(result.needs, [_github_need()])

    def test_declined_choice_saves_the_field_empty_without_a_need(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "")]

        result = _run([_node("github", "")], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
        self.assertEqual(result.needs, [])

    def test_declined_choice_clears_a_credential_the_builder_added_anyway(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "")]

        result = _run([_node("github", str(GITHUB_WORK.id))], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")

    def test_new_node_without_a_choice_is_a_need(self) -> None:
        result = _run([_node("github")])

        self.assertEqual(result.needs, [_github_need()])

    def test_codex_needs_both_of_its_credentials(self) -> None:
        result = _run([_node("codex", label="fixBug")])

        self.assertEqual(
            [need.field for need in result.needs], ["credentialId", "githubCredentialId"]
        )
        self.assertEqual(result.needs[0].existing, ("codex-main",))

    def test_optional_field_is_never_a_need(self) -> None:
        result = _run([_node("rag", label="search")])

        self.assertEqual(result.needs, [])


class ExistingNodeTests(unittest.TestCase):
    def test_unchanged_value_is_kept_even_when_not_owned(self) -> None:
        """A shared credential the user picked earlier survives the edit."""
        shared_id = str(uuid.uuid4())
        previous = [_node("github", shared_id)]

        result = _run([_node("github", shared_id)], previous=previous)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], shared_id)

    def test_existing_node_without_a_credential_is_never_a_need(self) -> None:
        previous = [_node("github", "")]

        result = _run([_node("github", "")], previous=previous)

        self.assertEqual(result.needs, [])

    def test_garbage_written_over_an_existing_value_is_reverted(self) -> None:
        previous = [_node("github", str(GITHUB_WORK.id))]

        result = _run([_node("github", "YOUR_CREDENTIAL_ID")], previous=previous)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_node_matched_by_label_and_type_counts_as_existing(self) -> None:
        previous = [_node("github", "", node_id="old-id")]

        result = _run([_node("github", "", node_id="new-id")], previous=previous)

        self.assertEqual(result.needs, [])

    def test_type_change_makes_the_node_new(self) -> None:
        previous = [_node("slack", "", label="notify")]

        result = _run([_node("github", "", label="notify")], previous=previous)

        self.assertEqual(result.needs, [_github_need("notify")])


class OffModeTests(unittest.TestCase):
    def test_new_nodes_get_no_credential_and_are_listed_for_the_ui(self) -> None:
        result = _run([_node("github", str(GITHUB_WORK.id))], mode=OFF)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
        self.assertEqual(result.needs, [_github_need()])

    def test_existing_nodes_keep_their_old_value_whatever_the_builder_wrote(self) -> None:
        previous = [_node("github", str(GITHUB_WORK.id))]

        result = _run([_node("github", str(GITHUB_OTHER.id))], previous=previous, mode=OFF)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))
        self.assertEqual(result.needs, [])

    def test_choices_are_ignored(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "github-work")]

        result = _run([_node("github", "")], choices=choices, mode=OFF)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")


class ChoiceParsingTests(unittest.TestCase):
    def test_valid_entries_are_parsed_and_malformed_ones_skipped(self) -> None:
        raw = [
            {"credential_type": "github", "credential_name": " github-work "},
            {
                "credential_type": "google_sheets",
                "credential_name": "sheet",
                "header_key": "Authorization",
            },
            {"credential_type": "slack", "credential_name": ""},
            {"credential_type": "not-a-type", "credential_name": "x"},
            "github",
            {"credential_name": "no-type"},
        ]

        self.assertEqual(
            parse_credential_choices(raw),
            [
                CredentialChoice(CredentialType.github, "github-work"),
                CredentialChoice(CredentialType.google_sheets, "sheet", "Authorization"),
                CredentialChoice(CredentialType.slack, ""),
            ],
        )

    def test_non_list_is_empty(self) -> None:
        self.assertEqual(parse_credential_choices(None), [])
        self.assertEqual(parse_credential_choices({"credential_type": "github"}), [])

    def test_choices_render_as_builder_instructions(self) -> None:
        text = format_credential_choices(
            [
                CredentialChoice(CredentialType.github, "github-work"),
                CredentialChoice(CredentialType.google_sheets, "sheet", "Authorization"),
                CredentialChoice(CredentialType.slack, ""),
            ]
        )

        self.assertEqual(
            text,
            "Credential choices the user made:\n"
            "- github: use `github-work`\n"
            "- google_sheets: use `sheet` with header key `Authorization` for http requests\n"
            "- slack: no credential (leave the field empty, send http requests without "
            "authentication)",
        )
        self.assertEqual(format_credential_choices([]), "")


class PayloadTests(unittest.TestCase):
    def test_requires_credentials_payload_lists_needs_by_name_and_type(self) -> None:
        payload = requires_credentials_payload([_github_need()])

        self.assertEqual(payload["status"], "requires_credentials")
        self.assertEqual(
            payload["needs"],
            [
                {
                    "node": "fetchRepos",
                    "node_type": "github",
                    "field": "credentialId",
                    "credential_types": ["github"],
                    "existing": ["github-other", "github-work"],
                }
            ],
        )
        self.assertIn("credential_choices", payload["instructions"])

    def test_assign_in_ui_payload_is_empty_without_needs(self) -> None:
        self.assertEqual(credentials_to_assign_payload([]), {})

    def test_assign_in_ui_payload_names_nodes_and_types(self) -> None:
        payload = credentials_to_assign_payload([_github_need()])

        self.assertEqual(
            payload["credentials_to_assign_in_ui"],
            [{"node": "fetchRepos", "node_type": "github", "credential_types": ["github"]}],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_generated_credentials.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.generated_credentials'`.

- [ ] **Step 3: Implement the module**

Create `backend/app/services/generated_credentials.py`:

```python
"""Deterministic credential handling for workflows the chat builder generates.

The builder model is told which credentials to use; this pass makes the result safe no
matter what it wrote. Names become ids, foreign or wrong-type ids are dropped, the user's
choices fill empty fields, and a new node's required field nobody decided on is returned
as a need instead of being saved empty.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.db.models import CredentialType
from app.services.credential_catalog import (
    NODE_CREDENTIAL_FIELDS,
    CatalogCredential,
    CredentialField,
    CredentialPromptMode,
)

REQUIRES_CREDENTIALS_INSTRUCTIONS = (
    "The workflow was not saved. Ask one heym-clarify question per service: offer the "
    "existing credentials listed for it, an option to create one, and an option to continue "
    "without a credential. Then call this tool again with credential_choices."
)


@dataclass(frozen=True)
class CredentialChoice:
    """One answer the user gave in chat: a credential by name, or none."""

    credential_type: CredentialType
    credential_name: str
    header_key: str = ""


@dataclass(frozen=True)
class CredentialNeed:
    """A new node's required credential field that no choice covers."""

    node: str
    node_type: str
    field: str
    credential_types: tuple[str, ...]
    existing: tuple[str, ...]


@dataclass
class CredentialPassResult:
    """Nodes after the pass, and the fields that still need a decision."""

    nodes: list[dict[str, Any]]
    needs: list[CredentialNeed] = field(default_factory=list)


def parse_credential_choices(raw: object) -> list[CredentialChoice]:
    """Parse the `credential_choices` tool argument, skipping malformed entries."""
    if not isinstance(raw, list):
        return []
    choices: list[CredentialChoice] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            credential_type = CredentialType(str(item.get("credential_type") or ""))
        except ValueError:
            continue
        choices.append(
            CredentialChoice(
                credential_type=credential_type,
                credential_name=str(item.get("credential_name") or "").strip(),
                header_key=str(item.get("header_key") or "").strip(),
            )
        )
    return choices


def format_credential_choices(choices: list[CredentialChoice]) -> str:
    """Render choices as builder instructions, or "" when there are none."""
    if not choices:
        return ""
    lines = ["Credential choices the user made:"]
    for choice in choices:
        if not choice.credential_name:
            lines.append(
                f"- {choice.credential_type.value}: no credential (leave the field empty, "
                "send http requests without authentication)"
            )
            continue
        line = f"- {choice.credential_type.value}: use `{choice.credential_name}`"
        if choice.header_key:
            line += f" with header key `{choice.header_key}` for http requests"
        lines.append(line)
    return "\n".join(lines)


def _label(node: dict[str, Any]) -> str:
    data = node.get("data")
    label = data.get("label") if isinstance(data, dict) else None
    return str(label) if label else ""


def _previous_version(
    node: dict[str, Any], previous: list[dict[str, Any]]
) -> dict[str, Any] | None:
    node_type = node.get("type")
    for old in previous:
        if old.get("id") == node.get("id") and old.get("type") == node_type:
            return old
    label = _label(node)
    if not label:
        return None
    for old in previous:
        if old.get("type") == node_type and _label(old) == label:
            return old
    return None


def _canonical_uuid(text: str) -> str:
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return text


def _resolve(
    value: object,
    spec: CredentialField,
    owned_by_id: dict[str, CatalogCredential],
    owned_by_name: dict[str, CatalogCredential],
) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    credential = owned_by_id.get(_canonical_uuid(text)) or owned_by_name.get(text)
    if credential is None or credential.type not in spec.types:
        return ""
    return str(credential.id)


def _named_choice_ids(
    spec: CredentialField,
    choices: list[CredentialChoice],
    owned_by_name: dict[str, CatalogCredential],
) -> list[str]:
    ids: list[str] = []
    for choice in choices:
        if choice.credential_type not in spec.types or not choice.credential_name:
            continue
        credential = owned_by_name.get(choice.credential_name)
        if credential is None or credential.type not in spec.types:
            continue
        if str(credential.id) not in ids:
            ids.append(str(credential.id))
    return ids


def _declined(spec: CredentialField, choices: list[CredentialChoice]) -> bool:
    return any(c.credential_type in spec.types and not c.credential_name for c in choices)


def _restore(data: dict[str, Any], name: str, value: object) -> None:
    if value is None:
        data.pop(name, None)
    else:
        data[name] = value


def _need(
    node: dict[str, Any], spec: CredentialField, catalog: list[CatalogCredential]
) -> CredentialNeed:
    return CredentialNeed(
        node=_label(node) or str(node.get("id") or ""),
        node_type=str(node.get("type") or ""),
        field=spec.name,
        credential_types=tuple(sorted(t.value for t in spec.types)),
        existing=tuple(sorted(c.name for c in catalog if c.type in spec.types)),
    )


def apply_generated_credentials(
    nodes: list[dict[str, Any]],
    *,
    catalog: list[CatalogCredential],
    choices: list[CredentialChoice],
    previous_nodes: list[dict[str, Any]] | None,
    mode: CredentialPromptMode,
) -> CredentialPassResult:
    """Make every credential field of a generated workflow safe and deterministic.

    A node that already existed keeps an unchanged value, since that was the user's own
    choice. In OFF mode it keeps its old value whatever the builder wrote, and new nodes
    get no credential. Otherwise a value must be, or name, an owned credential of an
    accepted type; the user's choices fill empty fields; and a new node's required field
    that no choice covers becomes a need.
    """
    owned_by_id = {str(credential.id): credential for credential in catalog}
    owned_by_name = {credential.name: credential for credential in catalog}
    previous = [node for node in previous_nodes or [] if isinstance(node, dict)]
    result = copy.deepcopy(nodes)
    needs: list[CredentialNeed] = []
    for node in result:
        if not isinstance(node, dict):
            continue
        fields = NODE_CREDENTIAL_FIELDS.get(str(node.get("type") or ""), ())
        data = node.get("data")
        if not fields or not isinstance(data, dict):
            continue
        before = _previous_version(node, previous)
        old_data = before.get("data") if before is not None else None
        old_data = old_data if isinstance(old_data, dict) else {}
        for spec in fields:
            unchanged = data.get(spec.name) == old_data.get(spec.name)
            if before is not None and (mode is CredentialPromptMode.OFF or unchanged):
                _restore(data, spec.name, old_data.get(spec.name))
                continue
            if mode is CredentialPromptMode.OFF:
                data[spec.name] = ""
                if spec.required:
                    needs.append(_need(node, spec, catalog))
                continue
            resolved = _resolve(data.get(spec.name), spec, owned_by_id, owned_by_name)
            named = _named_choice_ids(spec, choices, owned_by_name)
            declined = not named and _declined(spec, choices)
            if before is None and len(named) == 1:
                resolved = named[0]
            elif before is None and declined:
                resolved = ""
            elif not resolved and len(named) == 1:
                resolved = named[0]
            if not resolved and before is not None and not declined:
                _restore(data, spec.name, old_data.get(spec.name))
                continue
            data[spec.name] = resolved
            if not resolved and spec.required and before is None and not declined:
                needs.append(_need(node, spec, catalog))
    return CredentialPassResult(nodes=result, needs=needs)


def _need_as_dict(need: CredentialNeed) -> dict[str, Any]:
    return {
        "node": need.node,
        "node_type": need.node_type,
        "field": need.field,
        "credential_types": list(need.credential_types),
        "existing": list(need.existing),
    }


def requires_credentials_payload(needs: list[CredentialNeed]) -> dict[str, Any]:
    """Tool result that asks the chat to collect credential choices before saving."""
    return {
        "status": "requires_credentials",
        "needs": [_need_as_dict(need) for need in needs],
        "instructions": REQUIRES_CREDENTIALS_INSTRUCTIONS,
    }


def credentials_to_assign_payload(needs: list[CredentialNeed]) -> dict[str, Any]:
    """Tell an MCP caller which nodes still need a credential set in the Heym UI."""
    if not needs:
        return {}
    return {
        "credentials_to_assign_in_ui": [
            {
                "node": need.node,
                "node_type": need.node_type,
                "credential_types": list(need.credential_types),
            }
            for need in needs
        ],
        "credentials_note": (
            "Credentials cannot be chosen over MCP. Set these in the Heym UI before running."
        ),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_generated_credentials.py -q`
Expected: all pass.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check app/services/generated_credentials.py tests/test_generated_credentials.py && uv run ruff format app/services/generated_credentials.py tests/test_generated_credentials.py`
Expected: clean.

---

## Task 3: Clarify protocol and the assistant prompt argument

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py` (`CLARIFY_PROTOCOL_PROMPT`, `build_assistant_prompt`)
- Modify: `backend/app/api/ai_assistant.py` (three `http_credentials_prompt=` call sites only)
- Test: `backend/tests/test_clarify_protocol_prompt.py`, `backend/tests/test_credential_catalog.py`, `backend/tests/test_http_credential_catalog.py`

- [ ] **Step 1: Add the failing tests**

Append to `TestClarifyProtocolConstant` in `backend/tests/test_clarify_protocol_prompt.py`:

```python
    def test_constant_documents_credential_create_options(self) -> None:
        """The answer format must match what ClarifyCard serializes for a created credential."""
        text = CLARIFY_PROTOCOL_PROMPT
        self.assertIn(
            '"create": {"type": "<credential type>", "name": "<suggested name>"}', text
        )
        self.assertIn('`Created credential "<name>" (<type>)`', text)

    def test_constant_documents_optional_questions(self) -> None:
        text = CLARIFY_PROTOCOL_PROMPT
        self.assertIn('`"optional": true`', text)
        self.assertIn("`(skipped)`", text)
```

In `backend/tests/test_credential_catalog.py`, add the import
`from app.services.workflow_dsl_prompt import build_assistant_prompt` and append to `CredentialsPromptTests`:

```python
    def test_assistant_prompt_places_the_section_before_the_clarify_protocol(self) -> None:
        section = format_credentials_prompt(self.credentials, ASK)

        prompt = build_assistant_prompt(credentials_prompt=section)

        self.assertIn(section, prompt)
        self.assertLess(prompt.index(section), prompt.index("## Clarification Protocol"))

    def test_assistant_prompt_has_no_section_by_default(self) -> None:
        self.assertNotIn("## Credentials\n", build_assistant_prompt())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_clarify_protocol_prompt.py tests/test_credential_catalog.py -q`
Expected: the four new tests FAIL (missing text; `unexpected keyword argument 'credentials_prompt'`).

- [ ] **Step 3: Extend `CLARIFY_PROTOCOL_PROMPT`**

In `backend/app/services/workflow_dsl_prompt.py`, replace:

```
- Each question: `id` (short slug), `text`, `type` ("single" | "multi" | "text"),
  optional `options` (string array), optional `allowOther` (boolean).
```

with:

```
- Each question: `id` (short slug), `text`, `type` ("single" | "multi" | "text"),
  optional `options` (strings, or the option objects below), optional `allowOther`
  (boolean), optional `optional` (boolean).
```

and replace:

```
  an input the user can edit, and the answer comes back as
  `label (<prefillLabel>: "<edited value>")`.
```

with:

```
  an input the user can edit, and the answer comes back as
  `label (<prefillLabel>: "<edited value>")`.
- A `single` question can offer to create a credential with an option
  `{"label": "...", "create": {"type": "<credential type>", "name": "<suggested name>"}}`.
  The user fills in a form you never see, and the answer comes back as
  `Created credential "<name>" (<type>)`.
- Set `"optional": true` on a question the workflow can be built without. Its input says
  "Optional", the user may skip it, and a skipped question comes back as `(skipped)`.
```

- [ ] **Step 4: Rename the prompt argument and its callers**

In `build_assistant_prompt`, rename the parameter and its use:

```python
    installed_plugins: list[dict] | None = None,
    credentials_prompt: str = "",
) -> str:
```

```python
    prompt += credentials_prompt
    prompt += CLARIFY_PROTOCOL_PROMPT
```

In `backend/app/api/ai_assistant.py`, change the keyword at the three `build_assistant_prompt(...)` call sites (create tool, edit tool, `workflow_assistant_stream`) from `http_credentials_prompt=` to `credentials_prompt=`; leave their values unchanged for now. In `backend/tests/test_http_credential_catalog.py` change `build_assistant_prompt(http_credentials_prompt=section)` to `build_assistant_prompt(credentials_prompt=section)`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_clarify_protocol_prompt.py tests/test_credential_catalog.py tests/test_http_credential_catalog.py tests/test_dashboard_chat_api.py tests/test_workflow_assistant_stream.py -q`
Expected: all pass, including `test_synced_dsl_prompt_stays_clean`.

- [ ] **Step 6: Checkpoint (no commit)**

Run: `uv run ruff check app/services/workflow_dsl_prompt.py app/api/ai_assistant.py tests`
Expected: clean.

---

## Task 4: Wire the catalog and the pass into the assistant endpoints and chat tools

**Files:**
- Modify: `backend/app/api/ai_assistant.py`
- Delete: `backend/app/services/http_credential_catalog.py`, `backend/tests/test_http_credential_catalog.py`
- Test: `backend/tests/test_dashboard_chat_api.py`, `backend/tests/test_workflow_assistant_stream.py`

- [ ] **Step 1: Update the existing tests to the new seams**

In `backend/tests/test_dashboard_chat_api.py`:

1. Imports become:

```python
from app.api.ai_assistant import (
    DashboardChatRequest,
    FileAttachment,
    _append_date_to_user_messages,
    _build_user_message,
    _build_workflow_builder_user_message,
    _build_workflow_editor_user_message,
    _extract_generated_workflow_config,
    _summarize_tool_result,
    create_and_run_generated_workflow_tool,
    dashboard_chat_stream,
    edit_and_run_generated_workflow_tool,
    stream_dashboard_chat,
)
from app.db.models import CredentialType, WebhookBodyMode, WorkflowAuthType, WorkflowVersion
from app.services.credential_catalog import CatalogCredential, CredentialPromptMode
from app.services.generated_credentials import CredentialChoice
from app.services.llm_trace import LLMTraceContext
```

2. Replace `_stub_http_credentials_prompt` with:

```python
def _stub_credential_catalog(test: unittest.TestCase) -> tuple[AsyncMock, AsyncMock]:
    """Stub the credential catalog queries, which a bare AsyncMock db cannot answer."""
    prompt_patcher = patch(
        "app.api.ai_assistant.build_credentials_prompt", AsyncMock(return_value="")
    )
    catalog_patcher = patch(
        "app.api.ai_assistant.load_credential_catalog", AsyncMock(return_value=[])
    )
    test.addCleanup(prompt_patcher.stop)
    test.addCleanup(catalog_patcher.stop)
    return prompt_patcher.start(), catalog_patcher.start()
```

3. In the `setUp` of `DashboardChatApiTests`, `DashboardChatWorkflowBuilderTests` and `DashboardChatAttachmentIntegrationTests`, replace
`self.http_credentials_prompt = _stub_http_credentials_prompt(self)` with
`self.credentials_prompt, self.credential_catalog = _stub_credential_catalog(self)`.

4. Rename `test_dashboard_chat_appends_http_credentials_section` to `test_dashboard_chat_appends_credentials_section`; its first line becomes `self.credentials_prompt.return_value = _HTTP_CREDENTIALS_SECTION` and its last assertion:

```python
        self.credentials_prompt.assert_awaited_once_with(
            db, current_user.id, CredentialPromptMode.ASK_AND_CREATE
        )
```

5. In `test_edit_generated_workflow_updates_same_workflow_without_running`, the owned-id query is gone, so only the version query hits the database:

```python
        db.execute = AsyncMock(side_effect=[max_version_result])
```

6. Replace `test_create_generated_workflow_builder_gets_http_credentials_without_asking` and `test_edit_generated_workflow_builder_gets_http_credentials_without_asking` with:

```python
    async def test_create_generated_workflow_builder_gets_the_catalog_without_asking(
        self,
    ) -> None:
        self.credential_catalog.return_value = [
            CatalogCredential(uuid.uuid4(), "google", CredentialType.google)
        ]
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = None
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.owner_id = user.id
        credential.type = CredentialType.openai
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=_MINIMAL_BUILDER_CONTENT))]
        client = MagicMock()
        client.chat.completions.create.return_value = response
        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        with (
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant.run_execute_workflow_tool", AsyncMock()),
        ):
            await create_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=client,
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                goal="Call the Google Maps API with credential google",
                inputs={},
                available_workflows=[],
                public_base_url="http://localhost",
            )

        system_prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("`$credentials.google`", system_prompt)
        self.assertIn("You cannot ask questions in this step", system_prompt)
        self.credential_catalog.assert_awaited_once_with(db, user.id)

    async def test_edit_generated_workflow_builder_gets_the_catalog_without_asking(
        self,
    ) -> None:
        self.credential_catalog.return_value = [
            CatalogCredential(uuid.uuid4(), "google", CredentialType.google)
        ]
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = None
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.owner_id = user.id
        credential.type = CredentialType.openai
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Google Lookup"
        workflow.description = "Calls a Google API."
        workflow.nodes = []
        workflow.edges = []
        workflow.auth_type = WorkflowAuthType.anonymous
        workflow.auth_header_key = None
        workflow.auth_header_value = None
        workflow.webhook_body_mode = WebhookBodyMode.generic
        workflow.cache_ttl_seconds = None
        workflow.rate_limit_requests = None
        workflow.rate_limit_window_seconds = None
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=_MINIMAL_BUILDER_CONTENT))]
        client = MagicMock()
        client.chat.completions.create.return_value = response
        db = MagicMock()
        max_version_result = MagicMock()
        max_version_result.scalar.return_value = 1
        db.execute = AsyncMock(side_effect=[max_version_result])
        db.flush = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.ai_assistant.run_execute_workflow_tool", AsyncMock()),
        ):
            await edit_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=client,
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                workflow_id=str(workflow.id),
                instructions="Authenticate the Google call with credential google",
                inputs={},
                available_workflows=[],
                public_base_url="http://localhost",
            )

        system_prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("`$credentials.google`", system_prompt)
        self.assertIn("You cannot ask questions in this step", system_prompt)
        self.credential_catalog.assert_awaited_once_with(db, user.id)
```

In `backend/tests/test_workflow_assistant_stream.py`: add `from app.services.credential_catalog import CredentialPromptMode`, rename the class/method to `WorkflowAssistantCredentialsTests.test_builder_prompt_includes_credentials_section`, and change the patch and assertion:

```python
            patch(
                "app.api.ai_assistant.build_credentials_prompt",
                AsyncMock(return_value=section),
            ) as credentials_prompt,
```

```python
        self.assertIn(section, captured["system_prompt"])
        credentials_prompt.assert_awaited_once_with(
            db, user.id, CredentialPromptMode.ASK_AND_CREATE
        )
```

- [ ] **Step 2: Add the new behavior tests**

Append to `backend/tests/test_dashboard_chat_api.py`, before `if __name__ == "__main__":`:

````python
_GITHUB_BUILDER_CONTENT = """
```json
{
  "name": "List My Repositories",
  "description": "Lists the user's GitHub repositories.",
  "nodes": [
    {
      "id": "repos",
      "type": "github",
      "position": {"x": 0, "y": 0},
      "data": {"label": "fetchRepos", "credentialId": "", "githubOperation": "listUserRepositories"}
    }
  ],
  "edges": []
}
```
"""


def _builder_client(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def _owner_and_llm_credential() -> tuple[MagicMock, MagicMock]:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.user_rules = None
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.owner_id = user.id
    credential.type = CredentialType.openai
    return user, credential


class DashboardChatCredentialChoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.credentials_prompt, self.credential_catalog = _stub_credential_catalog(self)
        self.github_work = CatalogCredential(uuid.uuid4(), "github-work", CredentialType.github)
        self.credential_catalog.return_value = [self.github_work]

    async def _create(self, client: MagicMock, **kwargs: object) -> tuple[dict, MagicMock]:
        user, credential = _owner_and_llm_credential()
        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        with patch(
            "app.api.ai_assistant.template_service.list_node_templates",
            AsyncMock(return_value=[]),
        ):
            raw = await create_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=client,
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                goal="List my GitHub repositories",
                inputs={},
                available_workflows=[],
                public_base_url="http://localhost",
                **kwargs,
            )
        return json.loads(raw), db

    async def test_undecided_new_node_is_not_saved(self) -> None:
        payload, db = await self._create(_builder_client(_GITHUB_BUILDER_CONTENT))

        self.assertEqual(payload["status"], "requires_credentials")
        self.assertEqual(payload["needs"][0]["node"], "fetchRepos")
        self.assertEqual(payload["needs"][0]["existing"], ["github-work"])
        db.add.assert_not_called()

    async def test_chosen_credential_is_wired_into_the_node(self) -> None:
        client = _builder_client(_GITHUB_BUILDER_CONTENT)

        payload, db = await self._create(
            client,
            credential_choices=[CredentialChoice(CredentialType.github, "github-work")],
        )

        self.assertEqual(payload["status"], "created")
        saved = db.add.call_args.args[0]
        self.assertEqual(saved.nodes[0]["data"]["credentialId"], str(self.github_work.id))
        user_message = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("- github: use `github-work`", user_message)

    async def test_declined_credential_saves_the_node_empty(self) -> None:
        payload, db = await self._create(
            _builder_client(_GITHUB_BUILDER_CONTENT),
            credential_choices=[CredentialChoice(CredentialType.github, "")],
        )

        self.assertEqual(payload["status"], "created")
        self.assertEqual(db.add.call_args.args[0].nodes[0]["data"]["credentialId"], "")

    async def test_mcp_turn_saves_without_credentials_and_lists_them_for_the_ui(self) -> None:
        client = _builder_client(_GITHUB_BUILDER_CONTENT)

        payload, db = await self._create(
            client,
            credential_choices=[CredentialChoice(CredentialType.github, "github-work")],
            credential_mode=CredentialPromptMode.OFF,
        )

        self.assertEqual(payload["status"], "created")
        self.assertEqual(db.add.call_args.args[0].nodes[0]["data"]["credentialId"], "")
        self.assertEqual(
            payload["credentials_to_assign_in_ui"],
            [{"node": "fetchRepos", "node_type": "github", "credential_types": ["github"]}],
        )
        system_prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("You cannot use credentials in this step", system_prompt)
        self.assertNotIn("github-work", system_prompt)

    async def test_edit_does_not_ask_again_for_a_node_that_already_existed(self) -> None:
        user, credential = _owner_and_llm_credential()
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "List My Repositories"
        workflow.description = "Lists the user's GitHub repositories."
        workflow.nodes = [
            {
                "id": "repos",
                "type": "github",
                "position": {"x": 0, "y": 0},
                "data": {"label": "fetchRepos", "credentialId": ""},
            }
        ]
        workflow.edges = []
        workflow.auth_type = WorkflowAuthType.anonymous
        workflow.auth_header_key = None
        workflow.auth_header_value = None
        workflow.webhook_body_mode = WebhookBodyMode.generic
        workflow.cache_ttl_seconds = None
        workflow.rate_limit_requests = None
        workflow.rate_limit_window_seconds = None
        max_version_result = MagicMock()
        max_version_result.scalar.return_value = 1
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[max_version_result])
        db.flush = AsyncMock()

        with (
            patch("app.api.ai_assistant.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch(
                "app.api.ai_assistant.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
        ):
            raw = await edit_and_run_generated_workflow_tool(
                db=db,
                user=user,
                client=_builder_client(_GITHUB_BUILDER_CONTENT),
                model="gpt-4o-mini",
                selected_credential=credential,
                selected_model="gpt-4o-mini",
                workflow_id=str(workflow.id),
                instructions="Rename it",
                inputs={},
                available_workflows=[],
                public_base_url="http://localhost",
            )

        self.assertEqual(json.loads(raw)["status"], "edited")

    async def test_stream_hands_choices_and_mode_to_create_workflow(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        tool_message = MagicMock(content=None)
        tool_call = MagicMock()
        tool_call.id = "create-call"
        tool_call.function.name = "create_workflow"
        tool_call.function.arguments = json.dumps(
            {
                "goal": "List my GitHub repositories",
                "credential_choices": [
                    {"credential_type": "github", "credential_name": "github-work"}
                ],
            }
        )
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Added github-work, building it.", tool_calls=None)
        usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        selected = MagicMock(id=uuid.uuid4(), owner_id=user.id, type=CredentialType.openai)

        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.api.ai_assistant.create_and_run_generated_workflow_tool",
                AsyncMock(return_value=json.dumps({"status": "requires_credentials", "needs": []})),
            ) as create_tool,
        ):
            _ = [
                chunk
                async for chunk in stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "list my GitHub repositories"}],
                    AsyncMock(),
                    user,
                    "OpenAI",
                    "http://localhost",
                    selected_credential=selected,
                    credential_mode=CredentialPromptMode.OFF,
                )
            ]

        kwargs = create_tool.await_args.kwargs
        self.assertEqual(kwargs["credential_mode"], CredentialPromptMode.OFF)
        self.assertEqual(
            kwargs["credential_choices"],
            [CredentialChoice(CredentialType.github, "github-work")],
        )

    def test_requires_credentials_result_is_summarized_by_type(self) -> None:
        summary = _summarize_tool_result(
            "create_workflow",
            json.dumps(
                {
                    "status": "requires_credentials",
                    "needs": [{"credential_types": ["github"]}, {"credential_types": ["slack"]}],
                }
            ),
        )

        self.assertEqual(summary, "Needs credentials: github, slack")
````

- [ ] **Step 3: Delete the old catalog and run the tests to verify they fail**

```bash
rm app/services/http_credential_catalog.py tests/test_http_credential_catalog.py
```

Run: `uv run pytest tests/test_dashboard_chat_api.py tests/test_workflow_assistant_stream.py -q`
Expected: collection error in `app/api/ai_assistant.py` (`ModuleNotFoundError: app.services.http_credential_catalog`).

- [ ] **Step 4: Update the imports in `ai_assistant.py`**

Delete `from app.services.http_credential_catalog import build_http_credentials_prompt`. After `from app.services.credential_access import get_accessible_credential` add:

```python
from app.services.credential_catalog import (
    CredentialPromptMode,
    build_credentials_prompt,
    format_credentials_prompt,
    load_credential_catalog,
)
```

and after `from app.services.encryption import decrypt_config` add:

```python
from app.services.generated_credentials import (
    CredentialChoice,
    CredentialPassResult,
    apply_generated_credentials,
    credentials_to_assign_payload,
    format_credential_choices,
    parse_credential_choices,
    requires_credentials_payload,
)
```

- [ ] **Step 5: Add `credential_choices` to both tool schemas**

In `DASHBOARD_CHAT_TOOLS`, add this property to the `parameters.properties` of **both** `create_workflow` and `edit_workflow` (leave `required` unchanged):

```python
                    "credential_choices": {
                        "type": "array",
                        "description": "The user's credential answers from the heym-clarify card, one per service. Use an empty credential_name when the user chose to continue without a credential. Add header_key for http calls.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "credential_type": {
                                    "type": "string",
                                    "description": "Credential type, for example github or google_sheets.",
                                },
                                "credential_name": {
                                    "type": "string",
                                    "description": "Name of the chosen or created credential; empty for none.",
                                },
                                "header_key": {
                                    "type": "string",
                                    "description": "Header key for http requests, for example Authorization.",
                                },
                            },
                            "required": ["credential_type", "credential_name"],
                        },
                    },
```

- [ ] **Step 6: Trim `_sanitize_generated_workflow_nodes` and drop the old set**

Delete the `_INTEGRATION_CREDENTIAL_NODE_TYPES = {...}` constant and the `_get_owned_credential_ids` function. In `_sanitize_generated_workflow_nodes`, change the docstring and the integration branch:

```python
    """Clear unsafe generated LLM credentials and fill LLM nodes from the selected credential.

    Integration credential fields go through `apply_generated_credentials` instead.
    """
```

```python
        if node_type == "playwright":
            _clear_unowned_credential_field(data, "credentialId", owned_credential_ids)
```

- [ ] **Step 7: Helpers next to `_build_saved_workflow_payload`**

Give `_build_saved_workflow_payload` an `extra` keyword:

```python
    *,
    status_value: str,
    extra: dict[str, Any] | None = None,
) -> str:
```

and just before its `return json.dumps(payload, default=str)`:

```python
    if extra:
        payload.update(extra)
```

Then add below the function:

```python
def _builder_credential_mode(turn_mode: CredentialPromptMode) -> CredentialPromptMode:
    """The builder inside a chat tool never asks: it applies choices, or uses none on MCP."""
    if turn_mode is CredentialPromptMode.OFF:
        return CredentialPromptMode.OFF
    return CredentialPromptMode.APPLY_CHOICES


def _unassigned_credentials_extra(
    result: CredentialPassResult, builder_mode: CredentialPromptMode
) -> dict[str, Any] | None:
    if builder_mode is not CredentialPromptMode.OFF:
        return None
    return credentials_to_assign_payload(result.needs) or None
```

- [ ] **Step 8: Pass choices to the builder user messages**

Give both message builders a trailing optional parameter:

```python
def _build_workflow_builder_user_message(
    goal: str,
    inputs: dict[str, Any],
    attachment: FileAttachment | None,
    credential_choices: list[CredentialChoice] | None = None,
) -> str:
```

```python
def _build_workflow_editor_user_message(
    workflow: Workflow,
    instructions: str,
    inputs: dict[str, Any],
    attachment: FileAttachment | None,
    credential_choices: list[CredentialChoice] | None = None,
) -> str:
```

and in both, immediately before `return "\n".join(parts)`:

```python
    choices_text = format_credential_choices(credential_choices or [])
    if choices_text:
        parts.append("\n" + choices_text)
```

- [ ] **Step 9: Rewire `create_and_run_generated_workflow_tool`**

Add two keyword parameters after `cancel_event`:

```python
    cancel_event: Event | None = None,
    credential_choices: list[CredentialChoice] | None = None,
    credential_mode: CredentialPromptMode = CredentialPromptMode.ASK_AND_CREATE,
) -> str:
```

Replace the `system_prompt = build_assistant_prompt(...)` statement and the `builder_messages = [...]` list with:

```python
        catalog = await load_credential_catalog(db, user.id)
        builder_mode = _builder_credential_mode(credential_mode)
        choices = [] if builder_mode is CredentialPromptMode.OFF else list(credential_choices or [])
        system_prompt = build_assistant_prompt(
            None,
            available_workflows,
            user.user_rules,
            available_node_templates=node_template_payload,
            installed_plugins=await _load_installed_plugins(db),
            credentials_prompt=format_credentials_prompt(catalog, builder_mode),
        )
        builder_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _build_workflow_builder_user_message(
                    goal, inputs, attachment, choices
                ),
            },
        ]
```

Replace the sanitize block (from `owned_credential_ids = await _get_owned_credential_ids(db, user.id)` through `edges = workflow_config["edges"]`) with:

```python
        nodes = _sanitize_generated_workflow_nodes(
            workflow_config["nodes"],
            owned_credential_ids={str(credential.id) for credential in catalog},
            selected_credential=selected_credential,
            selected_model=selected_model,
            user_id=user.id,
        )
        credential_pass = apply_generated_credentials(
            nodes, catalog=catalog, choices=choices, previous_nodes=None, mode=builder_mode
        )
        if credential_pass.needs and builder_mode is not CredentialPromptMode.OFF:
            return json.dumps(requires_credentials_payload(credential_pass.needs))
        nodes = credential_pass.nodes
        edges = workflow_config["edges"]
```

and the final return:

```python
        return _build_saved_workflow_payload(
            workflow,
            nodes,
            edges,
            input_fields,
            run_inputs,
            None,
            status_value="created",
            extra=_unassigned_credentials_extra(credential_pass, builder_mode),
        )
```

- [ ] **Step 10: Rewire `edit_and_run_generated_workflow_tool` the same way**

Add the same two keyword parameters. Replace its `system_prompt = build_assistant_prompt(...)` / `builder_messages` with:

```python
        catalog = await load_credential_catalog(db, user.id)
        builder_mode = _builder_credential_mode(credential_mode)
        choices = [] if builder_mode is CredentialPromptMode.OFF else list(credential_choices or [])
        system_prompt = build_assistant_prompt(
            current_workflow,
            available_workflows,
            user.user_rules,
            available_node_templates=node_template_payload,
            installed_plugins=await _load_installed_plugins(db),
            credentials_prompt=format_credentials_prompt(catalog, builder_mode),
        )
        builder_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _build_workflow_editor_user_message(
                    workflow, instructions, inputs, attachment, choices
                ),
            },
        ]
```

Replace its sanitize block (through `edges = workflow_config["edges"]`, before `workflow.name = ...`) with:

```python
        nodes = _sanitize_generated_workflow_nodes(
            workflow_config["nodes"],
            owned_credential_ids={str(credential.id) for credential in catalog},
            selected_credential=selected_credential,
            selected_model=selected_model,
            user_id=user.id,
        )
        credential_pass = apply_generated_credentials(
            nodes, catalog=catalog, choices=choices, previous_nodes=old_nodes, mode=builder_mode
        )
        if credential_pass.needs and builder_mode is not CredentialPromptMode.OFF:
            return json.dumps(requires_credentials_payload(credential_pass.needs))
        nodes = credential_pass.nodes
        edges = workflow_config["edges"]
```

and in its final `_build_saved_workflow_payload(...)` add `extra=_unassigned_credentials_extra(credential_pass, builder_mode),` after `status_value="edited",`.

- [ ] **Step 11: Thread mode and choices through `stream_dashboard_chat`**

Add the keyword parameter:

```python
    *,
    system_prompt_parts: Any | None = None,
    credential_mode: CredentialPromptMode = CredentialPromptMode.ASK_AND_CREATE,
) -> AsyncGenerator[str, None]:
```

In the `create_workflow` branch, after `inputs = ...` add `choices = parse_credential_choices(args.get("credential_choices"))`; pass `credential_choices=choices, credential_mode=credential_mode,` to `create_and_run_generated_workflow_tool(...)`; and set

```python
                        tool_request = {
                            "goal": goal,
                            "inputs": inputs,
                            "credential_choices": args.get("credential_choices") or [],
                        }
```

Do the same in the `edit_workflow` branch (parse after its `inputs = ...`, pass both keywords, add `"credential_choices": args.get("credential_choices") or []` to its `tool_request`).

In `_emit_context`, count the credentials block under `system`:

```python
            breakdown = _context_breakdown(
                base_system_prompt=system_prompt_parts.base_system_prompt
                + getattr(system_prompt_parts, "credentials_block", ""),
```

- [ ] **Step 12: Summarize `requires_credentials`**

In `_summarize_tool_result`, in both the `create_workflow` and `edit_workflow` branches, right after their `if data.get("error"):` return:

```python
        if data.get("status") == "requires_credentials":
            types = sorted(
                {
                    credential_type
                    for need in data.get("needs") or []
                    for credential_type in need.get("credential_types") or []
                }
            )
            return f"Needs credentials: {', '.join(types)}"[:200]
```

- [ ] **Step 13: Update the canvas and Docs chat endpoints**

In `workflow_assistant_stream`:

```python
            credentials_prompt=await build_credentials_prompt(
                db, current_user.id, CredentialPromptMode.ASK_AND_CREATE
            ),
```

In `dashboard_chat_stream`:

```python
    system_prompt += await build_credentials_prompt(
        db, current_user.id, CredentialPromptMode.ASK_AND_CREATE
    )
```

- [ ] **Step 14: Run the tests**

Run: `uv run pytest tests/test_dashboard_chat_api.py tests/test_workflow_assistant_stream.py tests/test_generated_credentials.py tests/test_credential_catalog.py tests/test_clarify_protocol_prompt.py -q`
Expected: all pass.

Run: `grep -rn "http_credential\|_get_owned_credential_ids\|_INTEGRATION_CREDENTIAL_NODE_TYPES\|build_http_credentials_prompt" app tests`
Expected: no output.

- [ ] **Step 15: Checkpoint (no commit)**

Run: `uv run ruff check . && uv run ruff format .`
Expected: clean.

---

## Task 5: Chat tab credential mode per turn

**Files:**
- Modify: `backend/app/api/chats.py`
- Create: `backend/tests/test_chat_credential_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chat_credential_mode.py`:

```python
"""Chat tab turns get the credential flow; MCP turns never do."""

import contextlib
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chats
from app.services.credential_catalog import CredentialPromptMode

SECTION = "\n\n## Credentials\n\nCATALOG\n"


class ChatSystemPromptCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def _parts(
        self, mode: CredentialPromptMode
    ) -> tuple[chats.SystemPromptParts, AsyncMock]:
        user = SimpleNamespace(id=uuid.uuid4(), user_rules="")
        with (
            patch.object(chats, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])),
            patch.object(chats, "_load_agents_md_content", return_value=""),
            patch.object(
                chats, "build_credentials_prompt", AsyncMock(return_value=SECTION)
            ) as build,
        ):
            parts = await chats._assemble_system_prompt_parts(
                user,
                AsyncMock(),
                include_attachment_instructions=False,
                credential_mode=mode,
            )
        return parts, build

    async def test_ui_turns_get_the_credentials_section(self) -> None:
        parts, build = await self._parts(CredentialPromptMode.ASK_AND_CREATE)

        self.assertIn("CATALOG", parts.full_system_prompt)
        self.assertEqual(parts.credentials_block, SECTION)
        build.assert_awaited_once()

    async def test_mcp_turns_get_no_credentials_section(self) -> None:
        parts, build = await self._parts(CredentialPromptMode.OFF)

        self.assertNotIn("CATALOG", parts.full_system_prompt)
        self.assertEqual(parts.credentials_block, "")
        build.assert_not_awaited()

    def test_turns_default_to_the_full_flow(self) -> None:
        turn = chats.ChatTurn(
            content="hi",
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            attachment_data=None,
            should_generate_title=False,
        )

        self.assertEqual(turn.credential_mode, CredentialPromptMode.ASK_AND_CREATE)


class MCPChatTurnCredentialModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_turns_run_with_credentials_off(self) -> None:
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            is_running=False,
            title=chats.DEFAULT_CONVERSATION_TITLE,
            has_unread=False,
            queue_paused_by_message_id=None,
            last_credential_id=None,
            last_model=None,
        )
        assistant_message = SimpleNamespace(content="Done.", tool_calls=[])
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=assistant_message))
        )

        @contextlib.asynccontextmanager
        async def fake_session_maker():
            yield session

        captured: dict[str, chats.ChatTurn] = {}

        async def fake_run_chat_turn(
            _conv_id: str, _user_id: uuid.UUID, turn: chats.ChatTurn, _base_url: str
        ) -> chats.ChatTurnResult:
            captured["turn"] = turn
            return chats.ChatTurnResult(False, uuid.uuid4())

        with (
            patch.object(chats, "async_session_maker", fake_session_maker),
            patch.object(
                chats,
                "_get_or_create_mcp_conversation",
                AsyncMock(return_value=(conversation, True)),
            ),
            patch.object(chats, "_run_chat_turn", side_effect=fake_run_chat_turn),
            patch.object(chats, "_finish_worker_state", AsyncMock()),
            patch.object(chats.registry, "create_task", AsyncMock()),
            patch.object(chats.registry, "finish", AsyncMock()),
        ):
            await chats.run_mcp_chat_turn(
                user_id=uuid.uuid4(),
                message="list my GitHub repositories",
                conversation_id=None,
                credential_id=uuid.uuid4(),
                model="gpt-4o",
                public_base_url="https://heym.test",
            )

        self.assertEqual(captured["turn"].credential_mode, CredentialPromptMode.OFF)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_chat_credential_mode.py -q`
Expected: FAIL (`app.api.chats` has no `build_credentials_prompt`; `unexpected keyword argument 'credential_mode'`; `ChatTurn` has no `credential_mode`).

- [ ] **Step 3: Implement**

In `backend/app/api/chats.py`, after `from app.services.credential_access import get_accessible_credential` add:

```python
from app.services.credential_catalog import CredentialPromptMode, build_credentials_prompt
```

Extend the dataclasses:

```python
@dataclass(frozen=True)
class ChatTurn:
    content: str
    credential_id: uuid.UUID
    model: str
    attachment_data: dict | None
    should_generate_title: bool
    # MCP turns never list, pick or create credentials; turns typed in the UI do.
    credential_mode: CredentialPromptMode = CredentialPromptMode.ASK_AND_CREATE
```

```python
@dataclass(frozen=True)
class SystemPromptParts:
    full_system_prompt: str
    base_system_prompt: str
    agents_md: str
    workflows_block: str
    user_rules: str
    credentials_block: str = ""
```

Change the head of `_assemble_system_prompt_parts`:

```python
async def _assemble_system_prompt_parts(
    user: User,
    db: AsyncSession,
    *,
    include_attachment_instructions: bool,
    credential_mode: CredentialPromptMode = CredentialPromptMode.ASK_AND_CREATE,
) -> SystemPromptParts:
    workflows = await get_workflows_for_user_with_inputs(db, user.id)
    workflows_block = _format_workflows_for_prompt(workflows)
    agents_md = _load_agents_md_content() or ""
    user_rules = (user.user_rules or "").strip()
    credentials_block = (
        ""
        if credential_mode is CredentialPromptMode.OFF
        else await build_credentials_prompt(db, user.id, credential_mode)
    )
```

In its body, after the `if workflows_block:` block and before `if user_rules:`, add `system_prompt += credentials_block`; in its `return SystemPromptParts(...)` add `credentials_block=credentials_block,`.

In `_run_chat_turn`, pass the turn's mode to both calls:

```python
            parts = await _assemble_system_prompt_parts(
                user,
                db,
                include_attachment_instructions=turn.attachment_data is not None,
                credential_mode=turn.credential_mode,
            )
```

```python
                credential,
                system_prompt_parts=parts,
                credential_mode=turn.credential_mode,
            ):
```

In `run_mcp_chat_turn`, add `credential_mode=CredentialPromptMode.OFF,` to the `ChatTurn(...)`.

In `get_context_summary`:

```python
    breakdown = _context_breakdown(
        base_system_prompt=parts.base_system_prompt + parts.credentials_block,
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_chat_credential_mode.py tests/test_dashboard_chat_api.py tests/test_mcp_chat_tool.py -q`
Expected: all pass.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check app/api/chats.py tests/test_chat_credential_mode.py && uv run ruff format app/api/chats.py tests/test_chat_credential_mode.py`
Expected: clean.

---

## Task 6: Advisory test: the catalog never carries a value

**Files:**
- Create: `backend/tests/test_advisory_credential_catalog_no_values.py`

- [ ] **Step 1: Write the test**

```python
"""The assistant's credential catalog must never carry a credential's value.

The catalog is sent to an LLM on every assistant turn. It may hold names, types and ids,
which are not secrets; a value would leak to the model provider and into chat history.
"""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.db.models import CredentialType
from app.services.credential_catalog import (
    CatalogCredential,
    CredentialPromptMode,
    format_credentials_prompt,
    load_credential_catalog,
)
from app.services.generated_credentials import (
    CredentialChoice,
    CredentialNeed,
    format_credential_choices,
    requires_credentials_payload,
)


class CatalogNeverCarriesValuesTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_query_selects_only_id_name_and_type(self) -> None:
        result = MagicMock()
        result.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        await load_credential_catalog(db, uuid.uuid4())

        statement = db.execute.await_args.args[0]
        self.assertEqual([c.name for c in statement.selected_columns], ["id", "name", "type"])

    def test_catalog_entries_have_no_field_for_a_value(self) -> None:
        self.assertEqual(set(CatalogCredential.__dataclass_fields__), {"id", "name", "type"})

    def test_off_mode_names_no_credential(self) -> None:
        credential = CatalogCredential(uuid.uuid4(), "github-work", CredentialType.github)

        prompt = format_credentials_prompt([credential], CredentialPromptMode.OFF)

        self.assertNotIn("github-work", prompt)
        self.assertNotIn(str(credential.id), prompt)

    def test_choices_and_needs_carry_names_only(self) -> None:
        text = format_credential_choices([CredentialChoice(CredentialType.github, "github-work")])
        payload = requires_credentials_payload(
            [CredentialNeed("fetchRepos", "github", "credentialId", ("github",), ("github-work",))]
        )

        self.assertIn("github-work", text)
        self.assertEqual(
            set(payload["needs"][0]),
            {"node", "node_type", "field", "credential_types", "existing"},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_advisory_credential_catalog_no_values.py -q`
Expected: all pass (the guards hold after Tasks 1-2).

- [ ] **Step 3: Full backend checkpoint (no commit)**

Run: `uv run ruff check . && uv run ruff format --check . && ./run_tests.sh`
Expected: clean lint, every backend test passes.

---

## Task 7: Clarify types and parser (`create`, `optional`, `created`)

**Files:**
- Modify: `frontend/src/types/clarify.ts`, `frontend/src/utils/parseClarify.ts`
- Test: `frontend/src/utils/parseClarify.test.ts`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/utils/parseClarify.test.ts`:

```ts
const createQuestion: ClarifyQuestion = {
  id: "github",
  text: "Which GitHub credential should I use?",
  type: "single",
  options: [
    { label: "github-work" },
    { label: "Create a new credential", create: { type: "github", name: "github-personal" } },
    { label: "Continue without" },
  ],
};

describe("credential create options", () => {
  it("keeps a create option with a known type and a name", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          {
            id: "github",
            text: "Which GitHub credential?",
            type: "single",
            options: [
              "github-work",
              { label: "Create a new credential", create: { type: "github", name: " github-personal " } },
            ],
          },
        ],
      }),
    );

    expect(questions?.[0].options?.[1]).toEqual({
      label: "Create a new credential",
      create: { type: "github", name: "github-personal" },
    });
  });

  it("falls back to a plain label for an unknown type, a blank name or an inherited key", () => {
    for (const create of [
      { type: "not-a-type", name: "x" },
      { type: "github", name: "  " },
      { type: "toString", name: "x" },
      "github",
    ]) {
      const questions = extractClarifyBlock(
        clarifyMessage({
          questions: [{ id: "q", text: "Pick", type: "single", options: [{ label: "Create", create }] }],
        }),
      );

      expect(questions?.[0].options).toEqual([{ label: "Create" }]);
    }
  });

  it("drops create options on multi-choice questions", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          {
            id: "q",
            text: "Pick",
            type: "multi",
            options: [{ label: "Create", create: { type: "github", name: "gh" } }],
          },
        ],
      }),
    );

    expect(questions?.[0].options).toEqual([{ label: "Create" }]);
  });

  it("sends the created credential's saved name and type", () => {
    const text = serializeAnswers(
      [createQuestion],
      [
        {
          id: "github",
          text: createQuestion.text,
          selected: ["Create a new credential"],
          other: "",
          created: { type: "github", name: "gh-renamed" },
        },
      ],
    );

    expect(text).toBe(
      '[Plan answers]\n- Which GitHub credential should I use? → Created credential "gh-renamed" (github)',
    );
  });
});

describe("optional questions", () => {
  it("keeps the optional flag", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({ questions: [{ id: "f", text: "Any label filter?", type: "text", optional: true }] }),
    );

    expect(questions?.[0].optional).toBe(true);
  });

  it("rejects a non-boolean optional flag", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({ questions: [{ id: "f", text: "Filter?", type: "text", optional: "yes" }] }),
    );

    expect(questions).toBeNull();
  });

  it("marks a skipped optional question", () => {
    const question: ClarifyQuestion = { id: "f", text: "Any label filter?", type: "text", optional: true };

    const text = serializeAnswers([question], [{ id: "f", text: question.text, selected: [], other: "" }]);

    expect(text).toBe("[Plan answers]\n- Any label filter? → (skipped)");
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run (from `frontend/`): `bunx vitest run src/utils/parseClarify.test.ts`
Expected: the new tests FAIL (`create` is dropped, `(no answer)` instead of `(skipped)`, the non-boolean `optional` is accepted).

- [ ] **Step 3: Extend the types**

Replace `frontend/src/types/clarify.ts` with:

```ts
import type { CredentialType } from "@/types/credential";

export type ClarifyQuestionType = "single" | "multi" | "text";

// A credential the user can create in a dialog instead of picking an existing one.
export interface ClarifyCredentialCreate {
  type: CredentialType;
  name: string;
}

export interface ClarifyOption {
  label: string;
  // Editable value shown once this option is picked; single-choice questions only.
  prefill?: string;
  // Opens the credential dialog preset to this type and name; single-choice questions only.
  create?: ClarifyCredentialCreate;
}

export interface ClarifyQuestion {
  id: string;
  text: string;
  type: ClarifyQuestionType;
  options?: ClarifyOption[];
  allowOther?: boolean;
  // Names the prefill input, e.g. "Header".
  prefillLabel?: string;
  // The workflow can be built without an answer.
  optional?: boolean;
}

export interface ClarifyPayload {
  questions: ClarifyQuestion[];
}

export interface ClarifyAnswer {
  id: string;
  text: string;
  // For single/multi: the chosen option label(s). For text: empty.
  selected: string[];
  // Free-text entered via "Other" or a text question.
  other: string;
  // The user's edit of the chosen option's prefill.
  prefill?: string;
  // The credential created through a `create` option.
  created?: ClarifyCredentialCreate;
}
```

- [ ] **Step 4: Extend the parser**

In `frontend/src/utils/parseClarify.ts`:

1. Imports and constants at the top:

```ts
import { jsonrepair } from "jsonrepair";

import type {
  ClarifyAnswer,
  ClarifyCredentialCreate,
  ClarifyOption,
  ClarifyPayload,
  ClarifyQuestion,
  ClarifyQuestionType,
} from "@/types/clarify";
import type { CredentialType } from "@/types/credential";

import { CREDENTIAL_TYPE_LABELS } from "@/types/credential";

const FENCE = "```heym-clarify";
const MAX_CREDENTIAL_NAME_LENGTH = 100;
const CREDENTIAL_TYPES = new Set<string>(Object.keys(CREDENTIAL_TYPE_LABELS));
```

2. Add `optional?: boolean;` to `RawClarifyQuestion`, and extend the return of `isValidQuestion`:

```ts
    (obj.prefillLabel === undefined || typeof obj.prefillLabel === "string") &&
    (obj.optional === undefined || typeof obj.optional === "boolean")
```

3. Replace `normalizeOption` with:

```ts
function parseCreate(value: unknown): ClarifyCredentialCreate | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { type, name } = value as Record<string, unknown>;
  if (typeof type !== "string" || !CREDENTIAL_TYPES.has(type)) return undefined;
  if (typeof name !== "string") return undefined;
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > MAX_CREDENTIAL_NAME_LENGTH) return undefined;
  return { type: type as CredentialType, name: trimmed };
}

function normalizeOption(option: unknown, singleChoice: boolean): ClarifyOption {
  if (!option || typeof option !== "object") return { label: String(option) };
  const raw = option as Record<string, unknown>;
  const normalized: ClarifyOption = { label: raw.label as string };
  if (singleChoice && typeof raw.prefill === "string") normalized.prefill = raw.prefill;
  const create = singleChoice ? parseCreate(raw.create) : undefined;
  if (create) normalized.create = create;
  return normalized;
}
```

4. In `validate`, add `optional: q.optional,` after `prefillLabel: q.prefillLabel,`.

5. Replace `serializeAnswers` with:

```ts
function answerLabel(q: ClarifyQuestion, label: string, a: ClarifyAnswer): string {
  const option = q.options?.find((o) => o.label === label);
  if (option?.create && a.created) {
    return `Created credential "${a.created.name}" (${a.created.type})`;
  }
  return withPrefill(q, label, a.prefill);
}

export function serializeAnswers(
  questions: ClarifyQuestion[],
  answers: ClarifyAnswer[],
): string {
  const byId = new Map(answers.map((a) => [a.id, a]));
  const lines = questions.map((q) => {
    const a = byId.get(q.id);
    const parts: string[] = [];
    if (a) {
      if (a.selected.length > 0) {
        parts.push(...a.selected.map((label) => answerLabel(q, label, a)));
      }
      if (a.other.trim()) parts.push(`Other: "${a.other.trim()}"`);
    }
    const empty = q.optional ? "(skipped)" : "(no answer)";
    const value = parts.length > 0 ? parts.join(", ") : empty;
    return `- ${q.text} → ${value}`;
  });
  return ["[Plan answers]", ...lines].join("\n");
}
```

- [ ] **Step 5: Run the tests**

Run: `bunx vitest run src/utils/parseClarify.test.ts`
Expected: all pass, old and new.

- [ ] **Step 6: Checkpoint (no commit)**

Run: `bun run typecheck`
Expected: clean.

---

## Task 8: OAuth popup composable and link

**Files:**
- Create: `frontend/src/components/Credentials/useOAuthPopup.ts`
- Create: `frontend/src/components/Credentials/OAuthAuthorizeLink.vue`

- [ ] **Step 1: Create the composable**

`frontend/src/components/Credentials/useOAuthPopup.ts`:

```ts
import { onBeforeUnmount, ref, type Ref } from "vue";

import type { Credential } from "@/types/credential";

import { credentialsApi } from "@/services/api";

const STATUS_POLL_MS = 2000;
const STATUS_POLL_LIMIT_MS = 10 * 60 * 1000;
const POPUP_CLOSED_POLL_MS = 500;

export interface OAuthPopupState {
  connecting: Ref<boolean>;
  connected: Ref<boolean>;
  connectedCredential: Ref<Credential | null>;
  error: Ref<string>;
}

export interface OAuthPopupConfig {
  windowName: string;
  features: string;
  successType: string;
  errorType: string;
  failureMessage: string;
  onConnected?: (credential: Credential) => void;
}

export interface OAuthPopup {
  /** The authorization page, shown as a link while the flow is open. */
  authUrl: Ref<string>;
  /** The credential this dialog session created, reused by a retry. */
  sessionCredentialId: Ref<string | null>;
  start: (
    prepare: () => Promise<string>,
    authorize: (credentialId: string) => Promise<{ auth_url: string }>,
  ) => Promise<void>;
  openAuthPage: () => void;
  reset: () => void;
}

export function isConnectedMaskedValue(maskedValue: string | null | undefined): boolean {
  return maskedValue === "connected" || !!maskedValue?.startsWith("connected (");
}

/**
 * One OAuth popup flow. The callback page posts to `window.opener`; when the page was
 * opened without one (blocked popup, copied link) the credential is polled instead.
 */
export function useOAuthPopup(state: OAuthPopupState, config: OAuthPopupConfig): OAuthPopup {
  const authUrl = ref("");
  const sessionCredentialId = ref<string | null>(null);
  let popup: Window | null = null;
  let credentialId = "";
  let finished = false;
  let checking = false;
  let statusDeadline = 0;
  let closedTimer: ReturnType<typeof setInterval> | null = null;
  let statusTimer: ReturnType<typeof setInterval> | null = null;

  function stopTimers(): void {
    if (closedTimer) clearInterval(closedTimer);
    if (statusTimer) clearInterval(statusTimer);
    closedTimer = null;
    statusTimer = null;
    window.removeEventListener("message", onMessage);
  }

  async function finishConnected(credential: Credential | null): Promise<void> {
    if (finished) return;
    finished = true;
    stopTimers();
    popup?.close();
    popup = null;
    authUrl.value = "";
    let connectedCredential = credential;
    if (!connectedCredential) {
      try {
        connectedCredential = await credentialsApi.get(credentialId);
      } catch {
        connectedCredential = null;
      }
    }
    state.connectedCredential.value = connectedCredential;
    state.connected.value = true;
    state.connecting.value = false;
    if (connectedCredential) config.onConnected?.(connectedCredential);
  }

  function finishFailed(message: string): void {
    if (finished) return;
    finished = true;
    stopTimers();
    state.connecting.value = false;
    state.error.value = message || config.failureMessage;
  }

  function onMessage(event: MessageEvent): void {
    if (event.origin !== window.location.origin || !popup || event.source !== popup) return;
    if (event.data?.type === config.successType && event.data.credentialId === credentialId) {
      void finishConnected(null);
    } else if (event.data?.type === config.errorType) {
      finishFailed(typeof event.data.message === "string" ? event.data.message : "");
    }
  }

  async function checkStatus(): Promise<void> {
    if (finished || checking) return;
    if (Date.now() > statusDeadline) {
      if (statusTimer) clearInterval(statusTimer);
      statusTimer = null;
      return;
    }
    checking = true;
    try {
      const credential = await credentialsApi.get(credentialId);
      if (isConnectedMaskedValue(credential.masked_value)) await finishConnected(credential);
    } catch {
      // A failed check is retried on the next tick.
    } finally {
      checking = false;
    }
  }

  function watchPopup(): void {
    if (closedTimer) clearInterval(closedTimer);
    closedTimer = setInterval(() => {
      if (popup && !popup.closed) return;
      if (closedTimer) clearInterval(closedTimer);
      closedTimer = null;
      // Keep `popup` for the source check: its success message can land after it closes.
      state.connecting.value = false;
    }, POPUP_CLOSED_POLL_MS);
  }

  function openAuthPage(): void {
    if (!authUrl.value || finished) return;
    popup = window.open(authUrl.value, config.windowName, config.features);
    if (!popup) return;
    state.connecting.value = true;
    watchPopup();
  }

  async function start(
    prepare: () => Promise<string>,
    authorize: (credentialId: string) => Promise<{ auth_url: string }>,
  ): Promise<void> {
    stopTimers();
    finished = false;
    state.connecting.value = true;
    state.error.value = "";
    const alreadyConnected = state.connected.value;
    try {
      credentialId = await prepare();
      const { auth_url: url } = await authorize(credentialId);
      authUrl.value = url;
      window.addEventListener("message", onMessage);
      // A reconnect starts from "connected", so only a new connection can be polled for.
      if (!alreadyConnected) {
        statusDeadline = Date.now() + STATUS_POLL_LIMIT_MS;
        statusTimer = setInterval(() => void checkStatus(), STATUS_POLL_MS);
      }
      state.connecting.value = false;
      openAuthPage();
    } catch (err) {
      finishFailed(err instanceof Error ? err.message : "");
    }
  }

  function reset(): void {
    stopTimers();
    popup = null;
    credentialId = "";
    finished = false;
    authUrl.value = "";
    sessionCredentialId.value = null;
  }

  onBeforeUnmount(stopTimers);

  return { authUrl, sessionCredentialId, start, openAuthPage, reset };
}
```

- [ ] **Step 2: Create the link component**

`frontend/src/components/Credentials/OAuthAuthorizeLink.vue`:

```vue
<script setup lang="ts">
import { ExternalLink } from "lucide-vue-next";

const props = defineProps<{ authUrl: string }>();

const emit = defineEmits<{ (e: "open"): void }>();
</script>

<template>
  <p class="text-xs text-muted-foreground">
    Popup didn't open?
    <a
      :href="props.authUrl"
      target="_blank"
      rel="opener"
      class="inline-flex items-center gap-1 text-primary underline"
      @click.prevent="emit('open')"
    >
      Open the authorization page
      <ExternalLink class="h-3 w-3" />
    </a>
  </p>
</template>
```

The click re-runs `window.open` from the user's gesture, which popup blockers allow and which keeps `window.opener` for the callback's `postMessage`. A middle-click or a copied link still completes through the status poll.

- [ ] **Step 3: Checkpoint (no commit)**

Run: `bun run lint && bun run typecheck`
Expected: clean.

---

## Task 9: CredentialDialog presets, OAuth flows and links

**Files:**
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Props and imports**

Add to the internal types block: `import type { OAuthPopup } from "@/components/Credentials/useOAuthPopup";`
Add to the internal code block (keep alphabetical by path):

```ts
import OAuthAuthorizeLink from "@/components/Credentials/OAuthAuthorizeLink.vue";
import { useOAuthPopup } from "@/components/Credentials/useOAuthPopup";
```

Extend `Props`:

```ts
interface Props {
  open: boolean;
  credential?: Credential | null;
  presetType?: CredentialType;
  presetName?: string;
  // Chat: finish as soon as an OAuth connection succeeds instead of waiting for Done.
  completeOnConnect?: boolean;
}
```

Add `const codexAuthorizeUrl = ref("");` after `const codexSignedInAccount = ref("");`.

- [ ] **Step 2: One flow per OAuth type**

Immediately after `const error = ref("");` (all refs the flows use are declared above it, and the `watch` on `props.open` comes after), add:

```ts
function completeOAuthConnection(credential: Credential): void {
  if (!props.completeOnConnect) return;
  emit("saved", credential);
  emit("close");
}

const googleFlowConfig = {
  features: "width=520,height=620",
  successType: "google-oauth-success",
  errorType: "google-oauth-error",
  failureMessage: "OAuth authorization failed",
  onConnected: completeOAuthConnection,
};

const gsOAuth = useOAuthPopup(
  {
    connecting: gsOAuthConnecting,
    connected: gsOAuthConnected,
    connectedCredential: gsConnectedCredential,
    error,
  },
  { ...googleFlowConfig, windowName: "google-oauth" },
);
const gdOAuth = useOAuthPopup(
  {
    connecting: gdOAuthConnecting,
    connected: gdOAuthConnected,
    connectedCredential: gdConnectedCredential,
    error,
  },
  { ...googleFlowConfig, windowName: "google-oauth" },
);
const bqOAuth = useOAuthPopup(
  {
    connecting: bqOAuthConnecting,
    connected: bqOAuthConnected,
    connectedCredential: bqConnectedCredential,
    error,
  },
  { ...googleFlowConfig, windowName: "bq-oauth" },
);
const linearOAuth = useOAuthPopup(
  {
    connecting: linearOAuthConnecting,
    connected: linearOAuthConnected,
    connectedCredential: linearConnectedCredential,
    error,
  },
  {
    windowName: "linear-oauth",
    features: "width=520,height=680",
    successType: "linear-oauth-success",
    errorType: "linear-oauth-error",
    failureMessage: "Linear OAuth authorization failed",
    onConnected: completeOAuthConnection,
  },
);
const notionOAuth = useOAuthPopup(
  {
    connecting: notionOAuthConnecting,
    connected: notionOAuthConnected,
    connectedCredential: notionConnectedCredential,
    error,
  },
  {
    windowName: "notion-oauth",
    features: "width=520,height=680",
    successType: "notion-oauth-success",
    errorType: "notion-oauth-error",
    failureMessage: "Notion OAuth authorization failed",
    onConnected: completeOAuthConnection,
  },
);

function resetOAuthFlows(): void {
  for (const flow of [gsOAuth, gdOAuth, bqOAuth, linearOAuth, notionOAuth]) flow.reset();
}

// Reuse the credential an earlier attempt in this dialog created: a second create fails
// on the unique name.
async function saveOAuthCredential(credentialType: CredentialType, flow: OAuthPopup): Promise<string> {
  const credentialId = props.credential?.id ?? flow.sessionCredentialId.value;
  if (credentialId) {
    await credentialsApi.update(credentialId, { name: name.value, config: buildConfig() });
    return credentialId;
  }
  const saved = await credentialsApi.create({
    name: name.value,
    type: credentialType,
    config: buildConfig(),
  });
  flow.sessionCredentialId.value = saved.id;
  return saved.id;
}
```

- [ ] **Step 3: Reset on open and close; apply the preset name; Codex link**

In `watch(() => props.open, (open) => { ... })`, make `resetOAuthFlows();` the first statement of the callback. In its new-credential (`else`) branch replace `name.value = "";` with `name.value = props.presetName ?? "";`.

In `resetCodexOAuthState()` add `codexAuthorizeUrl.value = "";`. In `startCodexSignIn()` after `codexOAuthState.value = state;` add `codexAuthorizeUrl.value = authorize_url;`.

- [ ] **Step 4: Replace the five start functions' tails**

In each of `startGoogleDriveOAuth`, `startGoogleSheetsOAuth`, `startBigQueryOAuth`, `startLinearOAuth` and `startNotionOAuth`, keep the two validation `if` blocks and replace everything after them (from `...OAuthConnecting.value = true;` to the end of the function) with the matching call:

```ts
  await gdOAuth.start(
    () => saveOAuthCredential("google_drive", gdOAuth),
    credentialsApi.googleDriveOAuthAuthorize,
  );
```

```ts
  await gsOAuth.start(
    () => saveOAuthCredential("google_sheets", gsOAuth),
    credentialsApi.googleSheetsOAuthAuthorize,
  );
```

```ts
  await bqOAuth.start(
    () => saveOAuthCredential("bigquery", bqOAuth),
    credentialsApi.bigQueryOAuthAuthorize,
  );
```

```ts
  await linearOAuth.start(
    () => saveOAuthCredential("linear", linearOAuth),
    credentialsApi.linearOAuthAuthorize,
  );
```

```ts
  await notionOAuth.start(
    () => saveOAuthCredential("notion", notionOAuth),
    credentialsApi.notionOAuthAuthorize,
  );
```

Delete `isTrustedOAuthMessage` (now unused).

- [ ] **Step 5: Template: disable Connect after success; show the link**

Google Sheets Connect button (repeat for `gd`, `bq`, `linear`, `notion` with their refs, inputs and handler):

```vue
            <Button
              type="button"
              variant="outline"
              size="sm"
              :loading="gsOAuthConnecting"
              :disabled="saving || gsOAuthConnecting || !gsClientId.trim() || !gsClientSecret.trim() || (gsOAuthConnected && !isEditing)"
              @click="startGoogleSheetsOAuth"
            >
              {{ gsOAuthConnected ? (isEditing ? 'Reconnect' : 'Connected') : 'Connect' }}
            </Button>
```

The other four buttons get the same two changes. Their exact `:disabled` values and labels:

| Flow | `:disabled` | Label |
|---|---|---|
| Google Drive | `saving \|\| gdOAuthConnecting \|\| !gdClientId.trim() \|\| !gdClientSecret.trim() \|\| (gdOAuthConnected && !isEditing)` | `{{ gdOAuthConnected ? (isEditing ? 'Reconnect' : 'Connected') : 'Connect' }}` |
| BigQuery | `saving \|\| bqOAuthConnecting \|\| !bqClientId.trim() \|\| !bqClientSecret.trim() \|\| (bqOAuthConnected && !isEditing)` | `{{ bqOAuthConnected ? (isEditing ? 'Reconnect' : 'Connected') : 'Connect' }}` |
| Linear | `saving \|\| linearOAuthConnecting \|\| !linearClientId.trim() \|\| !linearClientSecret.trim() \|\| (linearOAuthConnected && !isEditing)` | `{{ linearOAuthConnected ? (isEditing ? "Reconnect" : "Connected") : "Connect" }}` |
| Notion | `saving \|\| notionOAuthConnecting \|\| !notionClientId.trim() \|\| !notionClientSecret.trim() \|\| (notionOAuthConnected && !isEditing)` | `{{ notionOAuthConnected ? (isEditing ? "Reconnect" : "Connected") : "Connect" }}` |

(The `\|` in the table is Markdown escaping; the template uses plain `||`.)

Right after the element that holds each Connect row (the `flex items-center justify-between` div for the three Google types, the `flex items-center gap-3` div for Linear and Notion), add the link, for example:

```vue
          <OAuthAuthorizeLink
            v-if="gsOAuth.authUrl.value && !gsOAuthConnected"
            :auth-url="gsOAuth.authUrl.value"
            @open="gsOAuth.openAuthPage()"
          />
```

and in the same position for the other four flows:

```vue
          <OAuthAuthorizeLink
            v-if="gdOAuth.authUrl.value && !gdOAuthConnected"
            :auth-url="gdOAuth.authUrl.value"
            @open="gdOAuth.openAuthPage()"
          />
```

```vue
          <OAuthAuthorizeLink
            v-if="bqOAuth.authUrl.value && !bqOAuthConnected"
            :auth-url="bqOAuth.authUrl.value"
            @open="bqOAuth.openAuthPage()"
          />
```

```vue
          <OAuthAuthorizeLink
            v-if="linearOAuth.authUrl.value && !linearOAuthConnected"
            :auth-url="linearOAuth.authUrl.value"
            @open="linearOAuth.openAuthPage()"
          />
```

```vue
          <OAuthAuthorizeLink
            v-if="notionOAuth.authUrl.value && !notionOAuthConnected"
            :auth-url="notionOAuth.authUrl.value"
            @open="notionOAuth.openAuthPage()"
          />
```

Under the Codex paragraph that starts "A new tab opens the OpenAI sign-in.", add:

```vue
            <p
              v-if="codexAuthorizeUrl"
              class="text-xs text-muted-foreground"
            >
              Sign-in tab didn't open?
              <a
                :href="codexAuthorizeUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="text-primary underline"
              >Open the OpenAI sign-in page</a>
            </p>
```

- [ ] **Step 6: Checkpoint (no commit)**

Run: `bun run lint && bun run typecheck`
Expected: clean.

Manual check in `./run.sh`: Credentials tab → new Google Sheets credential → Connect opens the popup; after success the button reads "Connected" and is disabled. Block popups in the browser and confirm the link appears and completes the flow.

---

## Task 10: CredentialCreateButton

**Files:**
- Create: `frontend/src/components/Credentials/CredentialCreateButton.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { onMounted, ref, shallowRef, type Component } from "vue";
import { Check, KeyRound } from "lucide-vue-next";

import type { ClarifyCredentialCreate } from "@/types/clarify";
import type { Credential, CredentialType } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import { CREDENTIAL_TYPE_LABELS } from "@/types/credential";

const props = defineProps<{
  type: CredentialType;
  name: string;
  created?: ClarifyCredentialCreate;
  disabled?: boolean;
}>();

const emit = defineEmits<{ (e: "created", credential: Credential): void }>();

const dialogOpen = ref(false);
// Loaded on demand so the chat and editor bundles do not carry the credential dialog. It is
// mounted closed first: the dialog initializes its form when `open` turns true.
const dialogComponent = shallowRef<Component | null>(null);

onMounted(async () => {
  dialogComponent.value = (await import("@/components/Credentials/CredentialDialog.vue")).default;
});

function onSaved(credential: Credential): void {
  dialogOpen.value = false;
  emit("created", credential);
}
</script>

<template>
  <div class="flex items-center gap-2">
    <span
      v-if="props.created"
      class="inline-flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
    >
      <Check class="h-3.5 w-3.5" />
      Created {{ props.created.name }}
    </span>
    <Button
      v-else
      type="button"
      variant="outline"
      size="sm"
      :disabled="props.disabled || !dialogComponent"
      @click="dialogOpen = true"
    >
      <KeyRound class="h-3.5 w-3.5" />
      Create {{ CREDENTIAL_TYPE_LABELS[props.type] }} credential…
    </Button>
    <component
      :is="dialogComponent"
      v-if="dialogComponent"
      :open="dialogOpen"
      :preset-type="props.type"
      :preset-name="props.name"
      complete-on-connect
      @close="dialogOpen = false"
      @saved="onSaved"
    />
  </div>
</template>
```

- [ ] **Step 2: Checkpoint (no commit)**

Run: `bun run lint && bun run typecheck`
Expected: clean.

---

## Task 11: ClarifyCard create options and optional questions

**Files:**
- Modify: `frontend/src/components/ui/ClarifyCard.vue`

- [ ] **Step 1: Script**

Replace the `<script setup>` block with:

```vue
<script setup lang="ts">
import { computed, reactive } from "vue";

import type { ClarifyAnswer, ClarifyOption, ClarifyQuestion } from "@/types/clarify";
import type { Credential } from "@/types/credential";

import CredentialCreateButton from "@/components/Credentials/CredentialCreateButton.vue";

const props = defineProps<{
  questions: ClarifyQuestion[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: "submit", answers: ClarifyAnswer[]): void;
  (e: "credential-created", credential: Credential): void;
}>();

const state = reactive<Record<string, ClarifyAnswer>>({});

for (const q of props.questions) {
  state[q.id] = { id: q.id, text: q.text, selected: [], other: "", prefill: "" };
}

function selectSingle(q: ClarifyQuestion, option: ClarifyOption): void {
  if (props.disabled) return;
  // Single choice and free-text are mutually exclusive: picking a chip clears Other.
  state[q.id].selected = [option.label];
  state[q.id].other = "";
  state[q.id].prefill = option.prefill ?? "";
}

function toggleMulti(q: ClarifyQuestion, option: ClarifyOption): void {
  if (props.disabled) return;
  const sel = state[q.id].selected;
  const idx = sel.indexOf(option.label);
  if (idx >= 0) sel.splice(idx, 1);
  else sel.push(option.label);
}

function onOtherFocus(q: ClarifyQuestion): void {
  if (props.disabled) return;
  // Focusing Other on a single-choice question deselects the chip
  // (multi keeps its selections so Other can add to them).
  if (q.type !== "multi") {
    state[q.id].selected = [];
    state[q.id].prefill = "";
  }
}

function isSelected(q: ClarifyQuestion, option: ClarifyOption): boolean {
  return state[q.id].selected.includes(option.label);
}

function selectedPrefillOption(q: ClarifyQuestion): ClarifyOption | undefined {
  if (q.type !== "single") return undefined;
  return q.options?.find((o) => o.prefill !== undefined && isSelected(q, o));
}

function selectedCreateOption(q: ClarifyQuestion): ClarifyOption | undefined {
  if (q.type !== "single") return undefined;
  return q.options?.find((o) => o.create !== undefined && isSelected(q, o));
}

function isAnswered(q: ClarifyQuestion): boolean {
  const a = state[q.id];
  if (selectedCreateOption(q)) return a.created !== undefined;
  return a.selected.length > 0 || a.other.trim().length > 0;
}

function otherPlaceholder(q: ClarifyQuestion): string {
  if (q.type === "text") return q.optional ? "Optional" : "Your answer";
  return q.optional ? "Other… (optional)" : "Other…";
}

const canSubmit = computed(() => {
  if (props.disabled) return false;
  return props.questions.every((q) => q.optional || isAnswered(q));
});

function submit(): void {
  if (!canSubmit.value) return;
  emit(
    "submit",
    props.questions.map((q) => ({ ...state[q.id] })),
  );
}

function onCredentialCreated(q: ClarifyQuestion, credential: Credential): void {
  state[q.id].created = { type: credential.type, name: credential.name };
  emit("credential-created", credential);
  // Picking "create" was the answer; carry on once the credential exists.
  submit();
}
</script>
```

- [ ] **Step 2: Template**

After the existing prefill `<label ...>...</label>` block, add:

```vue
      <CredentialCreateButton
        v-if="selectedCreateOption(q)?.create"
        :type="selectedCreateOption(q)!.create!.type"
        :name="selectedCreateOption(q)!.create!.name"
        :created="state[q.id].created"
        :disabled="props.disabled"
        @created="(credential: Credential) => onCredentialCreated(q, credential)"
      />
```

and change the free-text input's placeholder to `:placeholder="otherPlaceholder(q)"`.

- [ ] **Step 3: Checkpoint (no commit)**

Run: `bun run lint && bun run typecheck`
Expected: clean.

---

## Task 12: Canvas builder: refresh credentials and sanitize every credential field

**Files:**
- Create: `frontend/src/utils/generatedCredentialFields.ts`, `frontend/src/utils/generatedCredentialFields.test.ts`
- Modify: `frontend/src/components/Panels/DebugPanel.vue`

- [ ] **Step 1: Write the failing test**

`frontend/src/utils/generatedCredentialFields.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { CredentialListItem } from "@/types/credential";
import type { WorkflowNode } from "@/types/workflow";

import {
  resolveOwnedCredentialId,
  sanitizeGeneratedCredentialFields,
} from "./generatedCredentialFields";

function credential(id: string, name: string, isShared = false): CredentialListItem {
  return {
    id,
    name,
    type: "github",
    masked_value: null,
    header_key: null,
    created_at: "2026-09-23T00:00:00Z",
    is_shared: isShared,
  };
}

const OWNED = credential("11111111-1111-1111-1111-111111111111", "github-work");
const SHARED = credential("22222222-2222-2222-2222-222222222222", "team-github", true);
const CREDENTIALS = [OWNED, SHARED];

function node(type: string, data: Record<string, unknown>): WorkflowNode {
  return {
    id: "n1",
    type,
    position: { x: 0, y: 0 },
    data: { label: "step", ...data },
  } as unknown as WorkflowNode;
}

function field(result: WorkflowNode, key: string): unknown {
  return (result.data as unknown as Record<string, unknown>)[key];
}

function sanitize(n: WorkflowNode, existing?: WorkflowNode): WorkflowNode {
  return sanitizeGeneratedCredentialFields(n, CREDENTIALS, existing);
}

describe("resolveOwnedCredentialId", () => {
  it("accepts an owned id or an exact owned name", () => {
    expect(resolveOwnedCredentialId(OWNED.id, [OWNED])).toBe(OWNED.id);
    expect(resolveOwnedCredentialId(" github-work ", [OWNED])).toBe(OWNED.id);
  });

  it("rejects anything else", () => {
    expect(resolveOwnedCredentialId("YOUR_CREDENTIAL_ID", [OWNED])).toBe("");
    expect(resolveOwnedCredentialId(42, [OWNED])).toBe("");
    expect(resolveOwnedCredentialId("", [OWNED])).toBe("");
  });
});

describe("sanitizeGeneratedCredentialFields", () => {
  it("keeps an owned id and rewrites an owned name", () => {
    expect(field(sanitize(node("github", { credentialId: OWNED.id })), "credentialId")).toBe(OWNED.id);
    expect(field(sanitize(node("github", { credentialId: "github-work" })), "credentialId")).toBe(OWNED.id);
  });

  it("clears shared, unknown and placeholder values", () => {
    for (const value of [SHARED.id, "33333333-3333-3333-3333-333333333333", "YOUR_CREDENTIAL_ID"]) {
      expect(field(sanitize(node("github", { credentialId: value })), "credentialId")).toBe("");
    }
  });

  it("covers secondary credential fields", () => {
    const result = sanitize(node("codex", { credentialId: "", githubCredentialId: "github-work" }));

    expect(field(result, "githubCredentialId")).toBe(OWNED.id);
  });

  it("keeps a value the node already had on the canvas, even a shared one", () => {
    const existing = node("github", { credentialId: SHARED.id });

    expect(field(sanitize(node("github", { credentialId: SHARED.id }), existing), "credentialId")).toBe(SHARED.id);
  });

  it("leaves llm and agent nodes to the model credential logic", () => {
    const llm = node("llm", { credentialId: "YOUR_CREDENTIAL_ID" });

    expect(sanitize(llm)).toBe(llm);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bunx vitest run src/utils/generatedCredentialFields.test.ts`
Expected: FAIL, cannot resolve `./generatedCredentialFields`.

- [ ] **Step 3: Implement the util**

`frontend/src/utils/generatedCredentialFields.ts`:

```ts
import type { CredentialListItem } from "@/types/credential";
import type { NodeData, WorkflowNode } from "@/types/workflow";

// `llm` and `agent` take the model credential the assistant runs on; DebugPanel fills them.
const MODEL_NODE_TYPES = new Set(["llm", "agent"]);

function isCredentialField(key: string): boolean {
  return key === "credentialId" || key.endsWith("CredentialId");
}

/** The owned credential id a generated value names (an id or an exact name), or "". */
export function resolveOwnedCredentialId(value: unknown, owned: CredentialListItem[]): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text) return "";
  const match = owned.find((c) => c.id === text) ?? owned.find((c) => c.name === text);
  return match?.id ?? "";
}

/**
 * Keep only owned credentials in an AI-generated node's credential fields. A value the node
 * already had on the canvas stays as it is: it was the user's own earlier choice.
 */
export function sanitizeGeneratedCredentialFields(
  node: WorkflowNode,
  credentials: CredentialListItem[],
  existing: WorkflowNode | undefined,
): WorkflowNode {
  if (MODEL_NODE_TYPES.has(node.type)) return node;
  const owned = credentials.filter((c) => !c.is_shared);
  const previous = (existing?.data ?? {}) as unknown as Record<string, unknown>;
  const data = { ...node.data } as unknown as Record<string, unknown>;
  for (const key of Object.keys(data)) {
    if (!isCredentialField(key)) continue;
    if (existing && previous[key] === data[key]) continue;
    data[key] = resolveOwnedCredentialId(data[key], owned);
  }
  return { ...node, data: data as unknown as NodeData };
}
```

- [ ] **Step 4: Run the test**

Run: `bunx vitest run src/utils/generatedCredentialFields.test.ts`
Expected: pass.

- [ ] **Step 5: Use it in DebugPanel**

In `frontend/src/components/Panels/DebugPanel.vue`:

1. Import in the internal code block: `import { sanitizeGeneratedCredentialFields } from "@/utils/generatedCredentialFields";`
2. Replace the whole `sanitizeIntegrationCredentialFields` function with:

```ts
function sanitizeIntegrationCredentialFields(node: WorkflowNode): WorkflowNode {
  const sanitized = sanitizeGeneratedCredentialFields(
    node,
    allCredentialsForSanitize.value,
    findMatchingExistingNode(node),
  );
  if (sanitized.type !== "playwright") {
    return sanitized;
  }
  const data = { ...sanitized.data };
  const sanitizePlaywrightSteps = (
    steps: PlaywrightStep[] | undefined,
  ): PlaywrightStep[] | undefined => {
    if (!Array.isArray(steps)) return steps;
    return steps.map((step) => {
      const s = step as { action?: string; credentialId?: string; model?: string };
      if (
        s.action === "aiStep" &&
        s.credentialId &&
        shouldClearIntegrationCredentialId(s.credentialId)
      ) {
        return { ...step, credentialId: "", model: "" };
      }
      return step;
    });
  };
  data.playwrightSteps = sanitizePlaywrightSteps(data.playwrightSteps);
  data.playwrightAuthFallbackSteps = sanitizePlaywrightSteps(data.playwrightAuthFallbackSteps);
  return { ...sanitized, data };
}
```

3. On the `<ClarifyCard ...>` in the template, add `@credential-created="() => void loadAllCredentialsForSanitize()"`.

- [ ] **Step 6: Checkpoint (no commit)**

Run: `bun run lint && bun run typecheck && bunx vitest run src/utils`
Expected: clean, tests pass.

---

## Task 13: Docs chat renders clarify cards

**Files:**
- Modify: `frontend/src/components/Docs/useDocsChatDialog.ts`, `frontend/src/components/Docs/DocsChatDialog.vue`

- [ ] **Step 1: Composable**

In `useDocsChatDialog.ts`:

1. Imports:

```ts
import { computed, nextTick, onUnmounted, reactive, ref, watch } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

import type { ClarifyAnswer, ClarifyQuestion } from "@/types/clarify";
import type { CredentialListItem, LLMModel } from "@/types/credential";
import { useAiDefaults } from "@/composables/useAiDefaults";
import { aiApi, credentialsApi } from "@/services/api";
import { extractClarifyBlock, serializeAnswers, stripClarifyBlock } from "@/utils/parseClarify";
```

2. After `const messages = ref<ChatMessage[]>([]);` add `const answeredClarify = reactive(new Set<string>());`.

3. Replace `handleSubmit` with:

```ts
  function canSend(): boolean {
    return !streaming.value && !!selectedCredentialId.value && !!selectedModel.value;
  }

  function sendText(text: string): void {
    messages.value.push({ id: crypto.randomUUID(), role: "user", content: text });
    const assistantId = crypto.randomUUID();
    messages.value.push({ id: assistantId, role: "assistant", content: "" });
    activeAssistantMessageId.value = assistantId;
    streaming.value = true;
    steps.value = [];
    const streamSequence = bumpStreamSequence();
    const abortController = new AbortController();
    activeAbortController.value = abortController;
    aiApi.dashboardChatStream(
      {
        credentialId: selectedCredentialId.value,
        model: selectedModel.value,
        message: text,
        conversationHistory: buildConversationHistory(),
        conversationId: conversationId.value,
        chatSurface: "documentation",
        userRules: props.docPath ? `The user is currently reading the Heym documentation page: /docs/${props.docPath}. Prioritize answers relevant to this page.` : undefined,
        clientLocalDatetime: new Date().toLocaleString(),
      },
      (chunk) => queueStreamChunk(assistantId, chunk, streamSequence),
      () => {
        void activeFlushPromise.finally(() => {
          if (streamSequence !== activeStreamSequence) return;
          streaming.value = false;
          activeAbortController.value = null;
          activeAssistantMessageId.value = null;
        });
      },
      (error) => {
        void activeFlushPromise.finally(() => {
          if (streamSequence !== activeStreamSequence) return;
          streaming.value = false;
          activeAbortController.value = null;
          activeAssistantMessageId.value = null;
          if (error.name === "AbortError") return;
          const message = messages.value.find((entry) => entry.id === assistantId);
          if (message && message.role === "assistant") message.content = message.content || `Error: ${error.message}`;
        });
      },
      abortController.signal,
      (label) => { steps.value = [...steps.value, label]; },
    );
  }

  function handleSubmit(): void {
    const text = inputText.value.trim();
    if (!text || !canSend()) return;
    inputText.value = "";
    sendText(text);
  }

  function clarifyFor(message: ChatMessage): ClarifyQuestion[] | null {
    if (message.role !== "assistant" || !message.content) return null;
    // A half-streamed block would render a half-built card.
    if (streaming.value && activeAssistantMessageId.value === message.id) return null;
    return extractClarifyBlock(message.content);
  }

  function renderAssistantMarkdown(message: ChatMessage): string {
    return renderMarkdown(clarifyFor(message) ? stripClarifyBlock(message.content) : message.content);
  }

  function handleClarifySubmit(message: ChatMessage, answers: ClarifyAnswer[]): void {
    const questions = clarifyFor(message);
    if (!questions || answeredClarify.has(message.id) || !canSend()) return;
    answeredClarify.add(message.id);
    sendText(serializeAnswers(questions, answers));
  }
```

4. In `resetSession`, add `answeredClarify.clear();`.

5. Add `answeredClarify`, `clarifyFor`, `renderAssistantMarkdown` and `handleClarifySubmit` to the returned object.

- [ ] **Step 2: Dialog template**

In `DocsChatDialog.vue` update the script imports:

```ts
import { Check, Copy, FileText, Loader2, Send, Square, Trash2, Wand2 } from "lucide-vue-next";

import type { ClarifyAnswer } from "@/types/clarify";

import { useDocsChatDialog } from "@/components/Docs/useDocsChatDialog";
import Button from "@/components/ui/Button.vue";
import ClarifyCard from "@/components/ui/ClarifyCard.vue";
import Dialog from "@/components/ui/Dialog.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
```

add `answeredClarify, clarifyFor, renderAssistantMarkdown, handleClarifySubmit,` to the destructuring, change the assistant markdown div to `v-html="renderAssistantMarkdown(message)"`, and add right after that div:

```vue
                <ClarifyCard
                  v-if="clarifyFor(message)"
                  :questions="clarifyFor(message)!"
                  :disabled="answeredClarify.has(message.id) || streaming"
                  @submit="(answers: ClarifyAnswer[]) => handleClarifySubmit(message, answers)"
                />
```

- [ ] **Step 3: Checkpoint (no commit)**

Run: `bun run lint && bun run typecheck && bunx vitest run src/components/Docs`
Expected: clean; the existing `useDocsChatDialog.test.ts` still passes.

---

## Task 14: Release tour entry

**Files (under `frontend/src/features/release-tour/`):**
- Modify: `releaseRegistry.ts`, `tourVisuals.ts`, `releaseTourMapper.test.ts`
- Create: `components/visuals/ChatCredentialsTourVisual.vue`
- Delete: `components/visuals/ClusterInstancesTourVisual.vue`

- [ ] **Step 1: Update the registry test (it will fail)**

The registry keeps five sections. Adding `chat-credentials` drops `cluster-load-distribution`, and the new release stays out of the catalog while `tourEnabled` is false. In `releaseTourMapper.test.ts`:

```ts
    expect(catalog?.slides.map((slide) => slide.id)).toEqual([
      "model-router",
      "decision-node",
      "responses-api",
      "rag-upsert-delete",
    ]);
```

When the release commit flips `tourEnabled` to true, `"chat-credentials"` goes first in this list.

Run: `bunx vitest run src/features/release-tour`
Expected: FAIL (still five slides).

- [ ] **Step 2: Registry**

In `releaseRegistry.ts`, delete the whole `releaseId: "2026.10"` entry and add at the top of `RELEASE_REGISTRY`:

```ts
  {
    releaseId: "2026.15",
    publishedAt: new Date("2026-09-23T00:00:00Z"),
    headline: "Add a credential without leaving the conversation",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["chat-credentials"],
    },
    sections: [
      {
        id: "chat-credentials",
        title: "Create the credential a workflow needs, right in chat",
        publishedAt: new Date("2026-09-23T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "When a workflow you ask for needs a credential, the assistant asks which one to use. If you have a fitting credential it is listed next to **Create a new credential**; if you have none, the assistant asks whether to create one. You can always continue without one. Creating opens the credential form in the conversation, preset to the right type and a suggested name.",
          },
          {
            type: "prose",
            markdown:
              "The values go straight to Heym. The model only learns the name and type, says it added the credential, and carries on building. OAuth credentials such as Google Sheets connect in a popup, with a link to open the authorization page yourself if the popup is blocked.",
          },
          {
            type: "prose",
            markdown:
              "It works in the canvas **AI Assistant**, the **Chat** tab (including the workflows Chat creates and edits for you) and **Chat with Heym**. When no node covers an operation, such as adding a tab to a Google Sheet, the assistant sends the same credential in an **HTTP** request.",
          },
        ],
        tour: {
          description:
            "Pick an existing credential or create one inside the conversation; the model sees only its name and type.",
          useCases: [
            "Ask for a GitHub workflow and add the missing token without leaving chat",
            "Connect a Google Sheets account through OAuth from the assistant's question",
            "Reach operations a node lacks through HTTP with the same credential",
          ],
          tourVisual: "chat-credentials",
          docTarget: {
            categoryId: "reference",
            slug: "credentials",
            title: "Credentials",
          },
        },
      },
    ],
  },
```

- [ ] **Step 3: Visual**

`components/visuals/ChatCredentialsTourVisual.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: the question · 1: create picked · 2: the form · 3: created, continuing.
const step = useCycleStep(4, 1700);

interface MockOption {
  label: string;
  active: boolean;
}

const options = computed<MockOption[]>(() => [
  { label: "github-work", active: false },
  { label: "Create a new credential", active: step.value >= 1 },
  { label: "Continue without", active: false },
]);
</script>

<template>
  <div class="w-full space-y-2 rounded-lg border border-border bg-card p-3">
    <div class="rounded-md bg-background px-2 py-1.5">
      <p class="text-[11px] font-medium text-foreground">
        Which GitHub credential should I use?
      </p>
      <div class="mt-1.5 flex flex-wrap gap-1">
        <span
          v-for="option in options"
          :key="option.label"
          class="rounded-full border px-2 py-0.5 text-[10px] transition-colors duration-500"
          :class="option.active ? 'border-primary bg-primary text-primary-foreground' : 'border-border text-muted-foreground'"
        >{{ option.label }}</span>
      </div>
    </div>

    <div
      class="rounded-md border border-border px-2 py-1.5 transition-opacity duration-500"
      :class="step >= 2 ? 'opacity-100' : 'opacity-30'"
    >
      <div class="mb-1 flex items-center justify-between">
        <span class="text-[11px] font-medium text-foreground">New credential</span>
        <span class="rounded bg-muted px-1 text-[9px] text-muted-foreground">GitHub</span>
      </div>
      <div class="space-y-1 text-[10px]">
        <div class="flex items-center gap-2">
          <span class="w-10 shrink-0 text-muted-foreground">Name</span>
          <span class="flex-1 truncate rounded bg-background px-1.5 py-0.5 font-mono text-foreground">github-personal</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="w-10 shrink-0 text-muted-foreground">Token</span>
          <span class="h-4 flex-1 rounded bg-background px-1.5 py-0.5 font-mono text-foreground">{{ step >= 2 ? "••••••••••••" : "" }}</span>
        </div>
      </div>
    </div>

    <div class="flex items-center justify-between text-[10px]">
      <span class="text-muted-foreground">The model sees the name, not the token</span>
      <span
        class="transition-opacity duration-500"
        :class="step >= 3 ? 'text-primary opacity-100' : 'text-muted-foreground opacity-40'"
      >Added github-personal, continuing &rarr;</span>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Register it and drop the old visual**

In `tourVisuals.ts`, remove the `ClusterInstancesTourVisual` import and its `"cluster-instances"` entry, add

```ts
import ChatCredentialsTourVisual from "@/features/release-tour/components/visuals/ChatCredentialsTourVisual.vue";
```

and the entry `"chat-credentials": ChatCredentialsTourVisual,` (keys stay sorted). Delete `components/visuals/ClusterInstancesTourVisual.vue`.

- [ ] **Step 5: Run the tests**

Run: `bunx vitest run src/features/release-tour && bun run lint && bun run typecheck`
Expected: pass, clean.

---

## Task 15: Documentation

**Files:** under `frontend/src/docs/content/`

- [ ] **Step 1: `reference/ai-assistant.md`**

Replace the bullet `- The names and types of your credentials that an HTTP node can send (never their values)` with
`- The names, types and ids of your own credentials (never their values)`. Replace the paragraph that starts "When a request needs an authenticated HTTP call" with:

```markdown
### Credentials

When a workflow needs a credential, the assistant asks before building it. If you have credentials of a fitting type it lists them together with **Create a new credential**; if you have none it asks whether to create one. Every question also lets you continue without a credential.

Choosing to create one opens the credential form in the panel, preset to the right type and a suggested name. The values go straight to Heym; the assistant only learns the name and type, then carries on and puts the new credential on the node. OAuth credentials (Google Sheets, Google Drive, BigQuery, Linear, Notion) connect in a popup, and a link to the authorization page appears in case the popup is blocked.

The assistant prefers a dedicated node. When no node covers an operation, such as adding a tab to a Google Sheet, it uses an HTTP request and writes the header line for the chosen credential. See [HTTP › Authenticating with Credentials](../nodes/http-node.md#authenticating-with-credentials).

Clarification questions that the workflow can do without say **Optional** in their input and can be skipped.
```

- [ ] **Step 2: `tabs/chat-tab.md`**

Replace the "Credentials in HTTP requests" feature bullet with:

```markdown
- **Credentials** – When a workflow Chat creates or edits needs a credential, Chat asks which one to use, offers to create a new one in the conversation, or lets you continue without. The model sees the credential's name and type, never its values. See [AI Assistant › Credentials](../reference/ai-assistant.md#credentials)
```

At the end of "Using Chat from an MCP Client", add:

```markdown
Over MCP, Chat does not list, pick or create credentials. Workflows it builds leave credential fields empty, and the reply names the nodes that need a credential so you can set them in the editor.
```

- [ ] **Step 3: `reference/chat-with-docs.md`**

Add under "What Context It Uses":

```markdown
- Clarification questions appear as cards, the same as in the [Chat tab](../tabs/chat-tab.md). When a workflow request needs a credential, you can pick one or create it from the card.
```

- [ ] **Step 4: `reference/credentials.md`**

Before `## Related`, add:

```markdown
## Creating Credentials from Chat

The [AI Assistant](./ai-assistant.md#credentials), the [Chat tab](../tabs/chat-tab.md) and [Chat with Heym](./chat-with-docs.md) can create a credential when a workflow needs one. The assistant suggests the type and a name, and the regular credential form opens in the conversation. The assistant only sees the name and type. `heym_chat` over [MCP](../tabs/mcp-tab.md) cannot create or choose credentials.
```

- [ ] **Step 5: `tabs/credentials-tab.md`**

After the Notion paragraph in "Adding Credentials", add:

```markdown
OAuth credentials open the provider's authorization page in a popup. If the browser blocks it, use the **Open the authorization page** link under the Connect button; the dialog notices when the connection completes. Once a new credential is connected, the button shows **Connected**.
```

- [ ] **Step 6: `tabs/mcp-tab.md`**

Before "### Credential and model" in the "Heym Chat Tool" section, add:

```markdown
Credentials stay in the UI: `heym_chat` never lists, chooses or creates them. When it builds or edits a workflow, new nodes that need a credential are left empty and the reply names them, so you can set them in the editor.
```

- [ ] **Step 7: `nodes/http-node.md`**

Add to the table in "Authenticating with Credentials":

```markdown
| GitHub, Notion, Sentry | The token | `-H "Authorization: Bearer $credentials.Name"` |
```

and append to the paragraph that starts "When the [AI Assistant]": ` If you have no fitting credential, the question offers to create one.`

- [ ] **Step 8: Checkpoint (no commit)**

Run: `bun run lint`, then skim the changed pages under `/docs` in `./run.sh`.

---

## Task 16: Full verification

- [ ] **Step 1: Backend and frontend checks**

From the repo root:

```bash
HEYM_OTEL_ENABLED=false HEYM_HTTP_ALLOW_PRIVATE_URLS=false SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh
```

Expected: frontend lint and typecheck, Ruff, and every backend test pass. Formatting-only diffs from `ruff format` stay in the working tree.

- [ ] **Step 2: Frontend unit tests**

```bash
cd frontend && bun run test
```

Expected: all Vitest specs pass.

- [ ] **Step 3: Manual smoke (`./run.sh`)**

1. Chat tab, no GitHub credential: "list my GitHub repositories" → the card asks whether to create one → Create… → the dialog is preset to GitHub and the suggested name → save → the card sends `Created credential …` → the reply says it added the credential → the workflow card opens a workflow whose GitHub node has the credential selected.
2. Same, with an existing GitHub credential: the card lists it plus Create and Continue without.
3. Canvas AI Assistant: the same request; the applied GitHub node keeps the new credential.
4. Docs chat: the same request renders a card, not raw JSON.
5. "Add a tab to my Google Sheet" with no Sheets credential: create through OAuth; repeat with popups blocked and use the link; repeat by middle-clicking the link (polling path). The HTTP node carries `Authorization: Bearer $credentials[...]`.
6. Credentials tab: new Google Sheets credential → Connect → after success the button reads "Connected" and is disabled.
7. `heym_chat` over MCP: the same GitHub request builds without asking; the reply names the node to set up in the UI; the saved node has no credential.
8. A clarification question marked optional shows "Optional" in its input and can be skipped.

- [ ] **Step 4: Report**

Summarize what passed and anything that did not. Leave everything uncommitted.
