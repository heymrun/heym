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
from app.services.workflow_dsl_prompt import build_assistant_prompt
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

    def test_ask_prompt_opens_the_form_for_a_plain_create_request(self) -> None:
        """ "Create a GitHub credential" must get the form, not directions to the tab."""
        prompt = format_credentials_prompt(self.credentials, ASK)

        self.assertIn("create, add or connect a credential", prompt)
        self.assertIn("never send them to the Credentials tab", prompt)

    def test_ask_prompt_offers_to_edit_a_listed_credential(self) -> None:
        prompt = format_credentials_prompt(self.credentials, ASK)

        self.assertIn('"edit": {"id": "<credential id>"}', prompt)
        self.assertIn('`Updated credential "<name>" (<type>)`', prompt)

    def test_apply_prompt_has_no_form_rules(self) -> None:
        prompt = format_credentials_prompt(self.credentials, APPLY)

        self.assertNotIn('"edit"', prompt)
        self.assertNotIn("Credentials tab", prompt)

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

    def test_assistant_prompt_places_the_section_before_the_clarify_protocol(self) -> None:
        section = format_credentials_prompt(self.credentials, ASK)

        prompt = build_assistant_prompt(credentials_prompt=section)

        self.assertIn(section, prompt)
        self.assertLess(prompt.index(section), prompt.index("## Clarification Protocol"))

    def test_assistant_prompt_has_no_section_by_default(self) -> None:
        self.assertNotIn("## Credentials\n", build_assistant_prompt())


if __name__ == "__main__":
    unittest.main()
