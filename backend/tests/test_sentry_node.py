import unittest

import httpx
from fastapi import HTTPException

from app.api.credentials import get_masked_value, validate_credential_config
from app.db.models import CredentialType
from app.services.sentry_service import SentryService
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT


class SentryCredentialTests(unittest.TestCase):
    def test_validate_requires_api_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.sentry, {})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("api_token", ctx.exception.detail)

    def test_validate_accepts_base_url(self) -> None:
        validate_credential_config(
            CredentialType.sentry,
            {"api_token": "sntrys_secret", "base_url": "https://sentry.example.com"},
        )

    def test_validate_rejects_invalid_base_url(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.sentry,
                {"api_token": "sntrys_secret", "base_url": "sentry.example.com"},
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("base_url", ctx.exception.detail)

    def test_masked_value_hides_api_token(self) -> None:
        masked = get_masked_value(CredentialType.sentry, {"api_token": "sntrys_1234567890"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "sntrys_1234567890")


class SentryServiceTests(unittest.TestCase):
    def _client(self, handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_list_issues_builds_expected_request(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization", "")
            return httpx.Response(200, json=[{"id": "1"}])

        service = SentryService(
            {"api_token": "sntrys_secret", "base_url": "https://sentry.example.com"},
            client=self._client(handler),
        )
        issues = service.list_issues(
            "acme",
            project_slug="web-app",
            query="is:unresolved",
            stats_period="14d",
            limit="10",
        )

        self.assertEqual(issues, [{"id": "1"}])
        self.assertEqual(seen["auth"], "Bearer sntrys_secret")
        self.assertIn("/api/0/organizations/acme/issues/", seen["url"])
        self.assertIn("project=web-app", seen["url"])
        self.assertIn("per_page=10", seen["url"])

    def test_create_release_sends_json_payload(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["payload"] = request.content
            return httpx.Response(201, json={"version": "app@1.0.0"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        release = service.create_release(
            "acme",
            "app@1.0.0",
            projects=["web-app"],
            refs=[{"repository": "acme/repo", "commit": "abc123"}],
        )

        self.assertEqual(release["version"], "app@1.0.0")
        self.assertIn("/api/0/organizations/acme/releases/", str(seen["url"]))
        self.assertIn(b'"projects":["web-app"]', seen["payload"])
        self.assertIn(b'"refs":[{"repository":"acme/repo","commit":"abc123"}]', seen["payload"])


class SentryDslPromptTests(unittest.TestCase):
    def test_prompt_mentions_sentry(self) -> None:
        self.assertIn('"type": "sentry"', WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("sentryOperation", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("sentryOrganizationSlug", WORKFLOW_DSL_SYSTEM_PROMPT)
