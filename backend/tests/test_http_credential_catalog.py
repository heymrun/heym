"""Credentials the workflow assistant may reference in an http node's curl."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.http_credential_catalog import (
    HTTP_CREDENTIAL_TYPES,
    HttpCredential,
    build_http_credentials_prompt,
    credential_reference,
    format_http_credentials_prompt,
    load_http_credentials,
)
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_dsl_prompt import build_assistant_prompt
from app.services.workflow_executor import WorkflowExecutor


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
        credential = HttpCredential("perplexity", CredentialType.bearer)

        self.assertEqual(credential.header_line(), "Authorization: $credentials.perplexity")

    def test_header_credential_is_sent_as_the_whole_line(self) -> None:
        credential = HttpCredential("burak31", CredentialType.header)

        self.assertIsNone(credential.header_key)
        self.assertEqual(credential.header_line(), "$credentials.burak31")

    def test_api_key_under_authorization_gets_bearer_prefix(self) -> None:
        credential = HttpCredential("openai", CredentialType.openai)

        self.assertEqual(credential.header_line(), "Authorization: Bearer $credentials.openai")

    def test_google_defaults_to_goog_api_key_header(self) -> None:
        credential = HttpCredential("google", CredentialType.google)

        self.assertEqual(credential.header_line(), "x-goog-api-key: $credentials.google")

    def test_chosen_key_replaces_the_default(self) -> None:
        google = HttpCredential("google", CredentialType.google)
        openai = HttpCredential("openai", CredentialType.openai)

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
        }
        cases = [
            (
                HttpCredential("perplexity", CredentialType.bearer),
                "authorization",
                "Bearer pplx-token-123",
            ),
            (HttpCredential("vendor", CredentialType.header), "x-api-key", "vendor-secret-456"),
            (
                HttpCredential("openai", CredentialType.openai),
                "authorization",
                "Bearer sk-openai-789",
            ),
            (HttpCredential("google", CredentialType.google), "x-goog-api-key", "AIzaSyExample000"),
            (HttpCredential("voice", CredentialType.elevenlabs), "xi-api-key", "eleven-key-111"),
            (
                HttpCredential("slack-general-crazy", CredentialType.bearer),
                "authorization",
                "Bearer hyphen-token-222",
            ),
            (
                HttpCredential("sheet", CredentialType.google_sheets),
                "authorization",
                "Bearer ya29.fresh-token",
            ),
        ]
        for credential, header, expected in cases:
            with self.subTest(credential=credential.name):
                headers = _sent_headers(credential.header_line(), credentials)

                self.assertEqual(headers.get(header), expected)


class CatalogScopeTests(unittest.TestCase):
    def test_credentials_usable_in_a_header_are_listed(self) -> None:
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
        ):
            with self.subTest(credential_type=credential_type):
                self.assertIn(credential_type, HTTP_CREDENTIAL_TYPES)

    def test_google_oauth_credentials_send_their_token_as_bearer(self) -> None:
        """Their `$credentials` value is a fresh access token for calls the node lacks."""
        credential = HttpCredential("sheet", CredentialType.google_sheets)

        self.assertEqual(credential.header_line(), "Authorization: Bearer $credentials.sheet")

    def test_types_without_a_usable_header_value_are_left_out(self) -> None:
        """Connection, webhook and service-account credentials belong to their own nodes."""
        for credential_type in (
            CredentialType.bigquery,
            CredentialType.smtp,
            CredentialType.redis,
            CredentialType.slack,
            CredentialType.github,
            CredentialType.codex,
            CredentialType.model_router,
        ):
            with self.subTest(credential_type=credential_type):
                self.assertNotIn(credential_type, HTTP_CREDENTIAL_TYPES)


class LoadHttpCredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_owned_credentials_by_name_and_type_only(self) -> None:
        user_id = uuid.uuid4()
        result = MagicMock()
        result.all.return_value = [
            ("google", CredentialType.google),
            ("perplexity", CredentialType.bearer),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        credentials = await load_http_credentials(db, user_id)

        self.assertEqual(
            credentials,
            [
                HttpCredential("google", CredentialType.google),
                HttpCredential("perplexity", CredentialType.bearer),
            ],
        )
        statement = db.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("credentials.owner_id", sql)
        self.assertIn("credentials.type IN", sql)
        self.assertNotIn("encrypted_config", sql)
        self.assertIn(user_id, statement.compile().params.values())

    async def test_prompt_is_empty_when_the_user_has_no_http_credentials(self) -> None:
        result = MagicMock()
        result.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        prompt = await build_http_credentials_prompt(db, uuid.uuid4(), interactive=True)

        self.assertEqual(prompt, "")


class HttpCredentialsPromptTests(unittest.TestCase):
    credentials = [
        HttpCredential("google", CredentialType.google),
        HttpCredential("burak31", CredentialType.header),
        HttpCredential("slack-general-crazy", CredentialType.bearer),
    ]

    def test_no_section_without_credentials(self) -> None:
        self.assertEqual(format_http_credentials_prompt([], interactive=True), "")

    def test_lists_reference_and_header_line_per_credential(self) -> None:
        prompt = format_http_credentials_prompt(self.credentials, interactive=True)

        self.assertIn("`$credentials.google`", prompt)
        self.assertIn("`x-goog-api-key: $credentials.google`", prompt)
        self.assertIn("`$credentials.burak31`", prompt)
        self.assertIn('`Authorization: $credentials["slack-general-crazy"]`', prompt)

    def test_interactive_prompt_asks_with_an_editable_header_key(self) -> None:
        prompt = format_http_credentials_prompt(self.credentials, interactive=True)

        self.assertIn("heym-clarify", prompt)
        self.assertIn('"prefillLabel": "Header"', prompt)
        self.assertIn('"prefill"', prompt)
        self.assertIn("No credential", prompt)
        self.assertIn("dedicated Heym node", prompt)

    def test_interactive_prompt_offers_only_credentials_that_fit_the_api(self) -> None:
        """A Google Sheets call must not be padded with unrelated credentials."""
        prompt = format_http_credentials_prompt(self.credentials, interactive=True)

        self.assertIn("Offer only the credentials that fit that API", prompt)
        self.assertIn("never pad the question with unrelated ones", prompt)

    def test_non_interactive_prompt_uses_the_named_credential_without_asking(self) -> None:
        prompt = format_http_credentials_prompt(self.credentials, interactive=False)

        self.assertNotIn('"prefillLabel"', prompt)
        self.assertIn("cannot ask", prompt)
        self.assertIn("dedicated Heym node", prompt)

    def test_assistant_prompt_places_the_section_before_the_clarify_protocol(self) -> None:
        section = format_http_credentials_prompt(self.credentials, interactive=True)

        prompt = build_assistant_prompt(http_credentials_prompt=section)

        self.assertIn(section, prompt)
        self.assertLess(prompt.index(section), prompt.index("## Clarification Protocol"))

    def test_assistant_prompt_has_no_section_by_default(self) -> None:
        self.assertNotIn("Credentials for HTTP requests", build_assistant_prompt())


if __name__ == "__main__":
    unittest.main()
