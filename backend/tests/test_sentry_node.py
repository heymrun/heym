import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import sentry_node
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

    def test_update_merge_preserves_existing_api_token_when_only_base_url_changes(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.sentry,
            {
                "api_token": "sntrys_old",
                "base_url": "https://old-sentry.example.com",
            },
            {
                "api_token": "",
                "base_url": "https://new-sentry.example.com",
            },
        )

        self.assertEqual(merged["api_token"], "sntrys_old")
        self.assertEqual(merged["base_url"], "https://new-sentry.example.com")

    def test_update_merge_preserves_existing_base_url_when_omitted(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.sentry,
            {
                "api_token": "sntrys_old",
                "base_url": "https://sentry.example.com",
            },
            {
                "api_token": "sntrys_new",
            },
        )

        self.assertEqual(merged["api_token"], "sntrys_new")
        self.assertEqual(merged["base_url"], "https://sentry.example.com")


class SentryServiceTests(unittest.TestCase):
    def _client(self, handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_list_issues_builds_expected_request(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            self.assertEqual(request.headers.get("Authorization", ""), "Bearer sntrys_secret")
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
        self.assertEqual(len(seen_urls), 1)
        self.assertIn("/api/0/organizations/acme/issues/", seen_urls[0])
        self.assertIn("project=web-app", seen_urls[0])
        self.assertIn("query=is%3Aunresolved", seen_urls[0])
        self.assertIn("per_page=10", seen_urls[0])

    def test_list_issues_can_send_empty_query_for_all_issues(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(200, json=[{"id": "1"}])

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        issues = service.list_issues("acme", query="", limit="5")

        self.assertEqual(issues, [{"id": "1"}])
        self.assertEqual(len(seen_urls), 1)
        self.assertIn("/api/0/organizations/acme/issues/", seen_urls[0])
        self.assertIn("query=", seen_urls[0])

    def test_connection_only_fetches_one_organization(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(200, json=[{"slug": "acme"}])

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        result = service.test_connection()

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["organizations"], [{"slug": "acme"}])
        self.assertIn("per_page=1", seen_urls[0])

    def test_get_issue_uses_organization_scoped_endpoint(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(200, json={"id": "123"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        issue = service.get_issue("acme", "123")

        self.assertEqual(issue, {"id": "123"})
        self.assertEqual(len(seen_urls), 1)
        self.assertIn("/api/0/organizations/acme/issues/123/", seen_urls[0])

    def test_update_issue_uses_organization_scoped_endpoint(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["payload"] = request.content
            return httpx.Response(200, json={"id": "123", "status": "resolved"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        issue = service.update_issue("acme", "123", status="resolved")

        self.assertEqual(issue["status"], "resolved")
        self.assertEqual(seen["method"], "PUT")
        self.assertIn("/api/0/organizations/acme/issues/123/", str(seen["url"]))
        self.assertIn(b'"status":"resolved"', seen["payload"])

    def test_delete_issue_uses_organization_scoped_endpoint(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            return httpx.Response(204)

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        issue = service.delete_issue("acme", "123")

        self.assertEqual(issue["deleted"], True)
        self.assertEqual(issue["issue_id"], "123")
        self.assertEqual(seen["method"], "DELETE")
        self.assertIn("/api/0/organizations/acme/issues/123/", str(seen["url"]))

    def test_request_list_follows_next_cursor(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            if "cursor=next-cursor" in str(request.url):
                return httpx.Response(200, json=[{"id": "2"}])
            return httpx.Response(
                200,
                json=[{"id": "1"}],
                headers={
                    "Link": '<https://sentry.example.com/api/0/organizations/acme/projects/?cursor=next-cursor>; rel="next"; results="true"; cursor="next-cursor"'
                },
            )

        service = SentryService(
            {"api_token": "secret", "base_url": "https://sentry.example.com"},
            client=self._client(handler),
        )
        projects = service.list_projects("acme", limit="2")

        self.assertEqual(projects, [{"id": "1"}, {"id": "2"}])
        self.assertEqual(len(seen_urls), 2)
        self.assertIn("cursor=next-cursor", seen_urls[1])

    def test_request_list_rejects_unexpected_response_shape(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"detail": "not a list"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))

        with self.assertRaisesRegex(ValueError, "unexpected response"):
            service.list_projects("acme")

    def test_request_list_rejects_non_object_items(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "1"}, "not-an-object"])

        service = SentryService({"api_token": "secret"}, client=self._client(handler))

        with self.assertRaisesRegex(ValueError, "unexpected response"):
            service.list_projects("acme")

    def test_normalize_limit_handles_infinity(self) -> None:
        self.assertEqual(SentryService._normalize_limit("inf"), 25)

    def test_error_message_truncates_large_response_body(self) -> None:
        response = httpx.Response(500, text="x" * 1200)

        message = SentryService._error_message(response)

        self.assertEqual(len(message), 1003)
        self.assertTrue(message.endswith("..."))

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

    def test_update_organization_sends_json_payload(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["payload"] = request.content
            return httpx.Response(200, json={"slug": "acme", "name": "Acme"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        organization = service.update_organization("acme", {"name": "Acme"})

        self.assertEqual(organization["name"], "Acme")
        self.assertEqual(seen["method"], "PUT")
        self.assertIn("/api/0/organizations/acme/", str(seen["url"]))
        self.assertIn(b'"name":"Acme"', seen["payload"])

    def test_project_read_update_delete_use_project_endpoint(self) -> None:
        seen: list[tuple[str, str, bytes]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url), request.content))
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(200, json={"slug": "web-app", "name": "Web App"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        project = service.get_project("acme", "web-app")
        updated_project = service.update_project("acme", "web-app", {"name": "Web App"})
        deleted_project = service.delete_project("acme", "web-app")

        self.assertEqual(project["slug"], "web-app")
        self.assertEqual(updated_project["name"], "Web App")
        self.assertEqual(deleted_project["deleted"], True)
        self.assertEqual([item[0] for item in seen], ["GET", "PUT", "DELETE"])
        for _, url, _payload in seen:
            self.assertIn("/api/0/projects/acme/web-app/", url)
        self.assertIn(b'"name":"Web App"', seen[1][2])

    def test_team_update_delete_use_team_endpoint(self) -> None:
        seen: list[tuple[str, str, bytes]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url), request.content))
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(200, json={"slug": "frontend", "name": "Frontend"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        team = service.update_team("acme", "frontend", {"name": "Frontend"})
        deleted_team = service.delete_team("acme", "frontend")

        self.assertEqual(team["name"], "Frontend")
        self.assertEqual(deleted_team["deleted"], True)
        self.assertEqual([item[0] for item in seen], ["PUT", "DELETE"])
        for _, url, _payload in seen:
            self.assertIn("/api/0/teams/acme/frontend/", url)
        self.assertIn(b'"name":"Frontend"', seen[0][2])

    def test_release_update_delete_use_release_endpoint(self) -> None:
        seen: list[tuple[str, str, bytes]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url), request.content))
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(200, json={"version": "app@1.0.0", "ref": "abc123"})

        service = SentryService({"api_token": "secret"}, client=self._client(handler))
        release = service.update_release("acme", "app@1.0.0", {"ref": "abc123"})
        deleted_release = service.delete_release("acme", "app@1.0.0")

        self.assertEqual(release["ref"], "abc123")
        self.assertEqual(deleted_release["deleted"], True)
        self.assertEqual([item[0] for item in seen], ["PUT", "DELETE"])
        for _, url, _payload in seen:
            self.assertIn("/api/0/organizations/acme/releases/app%401.0.0/", url)
        self.assertIn(b'"ref":"abc123"', seen[0][2])


class SentryNodeHandlerTests(unittest.TestCase):
    def _ctx(self, node_data: dict) -> NodeExecutionContext:
        executor = Mock()
        executor.evaluate_nonempty_message_template.side_effect = lambda value, _inputs, _node_id: (
            value
        )
        executor.evaluate_message_template.side_effect = lambda value, _inputs, _node_id: value
        executor._is_single_dollar_expression.return_value = False
        executor._get_accessible_credential.return_value = Mock(
            type=CredentialType.sentry,
            encrypted_config="encrypted",
        )
        return NodeExecutionContext(
            executor=executor,
            node_id="sentry-1",
            inputs={},
            allow_branch_skip=True,
            start_time=0,
            node={"id": "sentry-1", "data": node_data},
            node_type="sentry",
            node_data=node_data,
            node_label="sentry",
        )

    def test_create_release_rejects_non_object_refs(self) -> None:
        node_data = {
            "credentialId": "credential-id",
            "sentryOperation": "createRelease",
            "sentryOrganizationSlug": "acme",
            "sentryReleaseVersion": "app@1.0.0",
            "sentryReleaseProjects": '["web-app"]',
            "sentryReleaseRefs": '["not-an-object"]',
        }
        service = Mock()
        service.close = Mock()

        with (
            patch.object(sentry_node, "SessionLocal") as session_local,
            patch.object(sentry_node, "decrypt_config", return_value={"api_token": "secret"}),
            patch.object(sentry_node, "SentryService", return_value=service),
        ):
            session_local.return_value.__enter__.return_value = Mock()
            with self.assertRaisesRegex(ValueError, "sentryReleaseRefs"):
                sentry_node.execute(self._ctx(node_data))

        service.create_release.assert_not_called()
        service.close.assert_called_once()

    def test_update_project_uses_json_payload(self) -> None:
        node_data = {
            "credentialId": "credential-id",
            "sentryOperation": "updateProject",
            "sentryOrganizationSlug": "acme",
            "sentryProjectSlug": "web-app",
            "sentryPayload": '{"name":"Web App"}',
        }
        service = Mock()
        service.update_project.return_value = {"slug": "web-app", "name": "Web App"}
        service.close = Mock()

        with (
            patch.object(sentry_node, "SessionLocal") as session_local,
            patch.object(sentry_node, "decrypt_config", return_value={"api_token": "secret"}),
            patch.object(sentry_node, "SentryService", return_value=service),
        ):
            session_local.return_value.__enter__.return_value = Mock()
            result = sentry_node.execute(self._ctx(node_data))

        self.assertEqual(result["project"]["name"], "Web App")
        service.update_project.assert_called_once_with("acme", "web-app", {"name": "Web App"})
        service.close.assert_called_once()

    def test_update_project_rejects_empty_json_payload(self) -> None:
        node_data = {
            "credentialId": "credential-id",
            "sentryOperation": "updateProject",
            "sentryOrganizationSlug": "acme",
            "sentryProjectSlug": "web-app",
            "sentryPayload": "{}",
        }
        service = Mock()
        service.close = Mock()

        with (
            patch.object(sentry_node, "SessionLocal") as session_local,
            patch.object(sentry_node, "decrypt_config", return_value={"api_token": "secret"}),
            patch.object(sentry_node, "SentryService", return_value=service),
        ):
            session_local.return_value.__enter__.return_value = Mock()
            with self.assertRaisesRegex(ValueError, "non-empty JSON payload"):
                sentry_node.execute(self._ctx(node_data))

        service.update_project.assert_not_called()
        service.close.assert_called_once()

    def test_list_issues_preserves_empty_query(self) -> None:
        node_data = {
            "credentialId": "credential-id",
            "sentryOperation": "listIssues",
            "sentryOrganizationSlug": "acme",
            "sentryQuery": "",
            "sentryLimit": "25",
        }
        service = Mock()
        service.list_issues.return_value = [{"id": "1"}]
        service.close = Mock()

        with (
            patch.object(sentry_node, "SessionLocal") as session_local,
            patch.object(sentry_node, "decrypt_config", return_value={"api_token": "secret"}),
            patch.object(sentry_node, "SentryService", return_value=service),
        ):
            session_local.return_value.__enter__.return_value = Mock()
            result = sentry_node.execute(self._ctx(node_data))

        self.assertEqual(result["count"], 1)
        service.list_issues.assert_called_once_with(
            "acme",
            project_slug=None,
            query="",
            stats_period=None,
            limit="25",
        )
        service.close.assert_called_once()

    def test_delete_issue_operation_calls_service(self) -> None:
        node_data = {
            "credentialId": "credential-id",
            "sentryOperation": "deleteIssue",
            "sentryOrganizationSlug": "acme",
            "sentryIssueId": "123",
        }
        service = Mock()
        service.delete_issue.return_value = {"deleted": True, "issue_id": "123"}
        service.close = Mock()

        with (
            patch.object(sentry_node, "SessionLocal") as session_local,
            patch.object(sentry_node, "decrypt_config", return_value={"api_token": "secret"}),
            patch.object(sentry_node, "SentryService", return_value=service),
        ):
            session_local.return_value.__enter__.return_value = Mock()
            result = sentry_node.execute(self._ctx(node_data))

        self.assertEqual(result["issue"]["deleted"], True)
        service.delete_issue.assert_called_once_with("acme", "123")
        service.close.assert_called_once()


class SentryDslPromptTests(unittest.TestCase):
    def test_prompt_mentions_sentry(self) -> None:
        self.assertIn('"type": "sentry"', WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("sentryOperation", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("sentryOrganizationSlug", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("updateProject", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("deleteIssue", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("sentryPayload", WORKFLOW_DSL_SYSTEM_PROMPT)
