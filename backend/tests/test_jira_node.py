"""Unit tests for JiraService and the Jira node handler."""

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.jira_service import JiraService
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.jira_node import execute


def _response(
    payload: object | None = None,
    status_code: int = 200,
    method: str = "GET",
    url: str = "https://example.atlassian.net/rest/api/3/myself",
) -> httpx.Response:
    request = httpx.Request(method, url)
    if payload is None:
        return httpx.Response(status_code=status_code, request=request)
    return httpx.Response(status_code=status_code, json=payload, request=request)


class JiraServiceTests(unittest.TestCase):
    def test_get_myself_uses_basic_auth_and_base_url(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"accountId": "acct-1", "displayName": "Ada"})
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        result = service.get_myself()

        self.assertEqual(result["displayName"], "Ada")
        client.request.assert_called_once()
        self.assertEqual(
            client.request.call_args.args[:2],
            ("GET", "https://example.atlassian.net/rest/api/3/myself"),
        )
        self.assertEqual(client.request.call_args.kwargs["auth"], ("ada@example.com", "jira-token"))

    def test_create_issue_sends_adf_description_and_labels(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"id": "10001", "key": "ENG-1"},
            method="POST",
            url="https://example.atlassian.net/rest/api/3/issue",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        issue = service.create_issue(
            "ENG",
            "Bug",
            "Fix checkout",
            description="Checkout is broken",
            assignee_account_id="acct-1",
            labels=["automation"],
        )

        self.assertEqual(issue["key"], "ENG-1")
        fields = client.request.call_args.kwargs["json"]["fields"]
        self.assertEqual(fields["project"], {"key": "ENG"})
        self.assertEqual(fields["issuetype"], {"name": "Bug"})
        self.assertEqual(fields["summary"], "Fix checkout")
        self.assertEqual(fields["assignee"], {"accountId": "acct-1"})
        self.assertEqual(fields["labels"], ["automation"])
        self.assertEqual(fields["description"]["type"], "doc")
        self.assertEqual(len(fields["description"]["content"]), 1)

    def test_create_issue_sends_plain_text_description_for_api_v2(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"id": "10001", "key": "ENG-1"},
            method="POST",
            url="https://example.atlassian.net/rest/api/2/issue",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
                "api_version": "2",
            },
            client=client,
        )

        service.create_issue("ENG", "Bug", "Fix checkout", description="Checkout is broken")

        fields = client.request.call_args.kwargs["json"]["fields"]
        self.assertEqual(fields["description"], "Checkout is broken")

    def test_create_issue_uses_username_assignee_for_data_center(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"id": "10001", "key": "ENG-1"},
            method="POST",
            url="https://jira.example.com/rest/api/2/issue",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://jira.example.com",
                "deployment": "data_center",
            },
            client=client,
        )

        service.create_issue("ENG", "Bug", "Fix checkout", assignee_account_id="ada")

        fields = client.request.call_args.kwargs["json"]["fields"]
        self.assertEqual(fields["assignee"], {"name": "ada"})

    def test_list_projects_uses_array_endpoint_for_data_center(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            [
                {"id": "10000", "key": "ENG"},
                {"id": "10001", "key": "OPS"},
                {"id": "10002", "key": "DOCS"},
            ],
            url="https://jira.example.com/rest/api/2/project",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://jira.example.com",
                "deployment": "data_center",
            },
            client=client,
        )

        result = service.list_projects(limit=1, start_at=1)

        self.assertEqual(result["values"], [{"id": "10001", "key": "OPS"}])
        self.assertEqual(result["startAt"], 1)
        self.assertEqual(result["maxResults"], 1)
        self.assertEqual(result["total"], 3)
        self.assertFalse(result["isLast"])
        self.assertEqual(
            client.request.call_args.args[:2],
            ("GET", "https://jira.example.com/rest/api/2/project"),
        )
        self.assertIsNone(client.request.call_args.kwargs["params"])

    def test_create_issue_prefers_issue_type_id(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"id": "10001", "key": "ENG-1"},
            method="POST",
            url="https://example.atlassian.net/rest/api/3/issue",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        service.create_issue("ENG", "Bug", "Fix checkout", issue_type_id="10001")

        fields = client.request.call_args.kwargs["json"]["fields"]
        self.assertEqual(fields["issuetype"], {"id": "10001"})

    def test_search_issues_uses_bounded_default_jql(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"issues": [], "isLast": True}, method="POST")
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        service.search_issues("")

        self.assertEqual(
            client.request.call_args.kwargs["json"]["jql"],
            "updated >= -30d ORDER BY updated DESC",
        )

    def test_search_issues_uses_search_jql_post(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {
                "issues": [{"id": "10001", "key": "ENG-1"}],
                "nextPageToken": "token-2",
                "isLast": False,
            },
            method="POST",
            url="https://example.atlassian.net/rest/api/3/search/jql",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        result = service.search_issues(
            "project = ENG",
            25,
            next_page_token="token-1",
            fields=["key", "summary"],
        )

        self.assertEqual(result["nextPageToken"], "token-2")
        self.assertEqual(
            client.request.call_args.args[:2],
            ("POST", "https://example.atlassian.net/rest/api/3/search/jql"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["json"],
            {
                "jql": "project = ENG",
                "maxResults": 25,
                "fields": ["key", "summary"],
                "nextPageToken": "token-1",
            },
        )

    def test_search_issues_uses_offset_search_for_data_center(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"issues": [{"id": "10001", "key": "ENG-1"}], "startAt": 10, "total": 11},
            method="POST",
            url="https://jira.example.com/rest/api/2/search",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://jira.example.com",
                "deployment": "data_center",
            },
            client=client,
        )

        result = service.search_issues(
            "project = ENG",
            25,
            next_page_token="ignored-for-data-center",
            start_at=10,
            fields=["key", "summary"],
        )

        self.assertEqual(result["total"], 11)
        self.assertEqual(
            client.request.call_args.args[:2],
            ("POST", "https://jira.example.com/rest/api/2/search"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["json"],
            {
                "jql": "project = ENG",
                "maxResults": 25,
                "fields": ["key", "summary"],
                "startAt": 10,
            },
        )

    def test_adf_text_document_splits_newlines(self) -> None:
        document = JiraService._adf_text_document("line one\nline two")
        self.assertEqual(len(document["content"]), 2)
        self.assertEqual(document["content"][0]["content"][0]["text"], "line one")
        self.assertEqual(document["content"][1]["content"][0]["text"], "line two")

    def test_update_issue_requires_at_least_one_field(self) -> None:
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=MagicMock(),
        )

        with self.assertRaisesRegex(ValueError, "at least one field"):
            service.update_issue("ENG-1")

    def test_get_issue_changelog_uses_pagination(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"values": [{"id": "10001"}], "total": 1})
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        result = service.get_issue_changelog("ENG-1", limit=25, start_at=10)

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            client.request.call_args.args[:2],
            ("GET", "https://example.atlassian.net/rest/api/3/issue/ENG-1/changelog"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["params"], {"maxResults": 25, "startAt": 10}
        )

    def test_get_issue_changelog_uses_expanded_issue_for_api_v2(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {
                "changelog": {
                    "histories": [{"id": "10001"}, {"id": "10002"}, {"id": "10003"}],
                    "total": 3,
                }
            }
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
                "api_version": "2",
            },
            client=client,
        )

        result = service.get_issue_changelog("ENG-1", limit=1, start_at=1)

        self.assertEqual(result["histories"], [{"id": "10002"}])
        self.assertEqual(result["total"], 3)
        self.assertFalse(result["isLast"])
        self.assertEqual(
            client.request.call_args.args[:2],
            ("GET", "https://example.atlassian.net/rest/api/2/issue/ENG-1"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["params"],
            {"expand": "changelog", "fields": "none"},
        )

    def test_notify_issue_sends_recipient_payload(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(None, status_code=204, method="POST")
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        notified = service.notify_issue(
            "ENG-1",
            subject="Heads up",
            text_body="Issue changed",
            to={"watchers": True},
        )

        self.assertTrue(notified)
        self.assertEqual(
            client.request.call_args.args[:2],
            ("POST", "https://example.atlassian.net/rest/api/3/issue/ENG-1/notify"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["json"],
            {"subject": "Heads up", "textBody": "Issue changed", "to": {"watchers": True}},
        )

    def test_update_comment_sends_adf_body(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"id": "10001", "body": {}}, method="PUT")
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        comment = service.update_comment("ENG-1", "10001", "Updated")

        self.assertEqual(comment["id"], "10001")
        self.assertEqual(
            client.request.call_args.args[:2],
            ("PUT", "https://example.atlassian.net/rest/api/3/issue/ENG-1/comment/10001"),
        )
        self.assertEqual(client.request.call_args.kwargs["json"]["body"]["type"], "doc")

    def test_update_comment_sends_plain_text_body_for_api_v2(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"id": "10001", "body": "Updated"}, method="PUT")
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
                "api_version": "2",
            },
            client=client,
        )

        service.update_comment("ENG-1", "10001", "Updated")

        self.assertEqual(client.request.call_args.kwargs["json"]["body"], "Updated")

    def test_create_user_sends_optional_fields(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"accountId": "acct-1"}, method="POST")
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        user = service.create_user(
            "ada@example.com",
            username="ada",
            display_name="Ada",
            products=["jira-software"],
        )

        self.assertEqual(user["accountId"], "acct-1")
        self.assertEqual(
            client.request.call_args.args[:2],
            ("POST", "https://example.atlassian.net/rest/api/3/user"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["json"],
            {
                "emailAddress": "ada@example.com",
                "displayName": "Ada",
                "products": ["jira-software"],
            },
        )

    def test_get_and_delete_user_use_username_for_data_center(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _response({"name": "ada"}, url="https://jira.example.com/rest/api/2/user"),
            _response(None, status_code=204, method="DELETE"),
        ]
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://jira.example.com",
                "deployment": "data_center",
            },
            client=client,
        )

        user = service.get_user("ada")
        deleted = service.delete_user("ada")

        self.assertEqual(user["name"], "ada")
        self.assertTrue(deleted)
        self.assertEqual(client.request.call_args_list[0].kwargs["params"], {"username": "ada"})
        self.assertEqual(client.request.call_args_list[1].kwargs["params"], {"username": "ada"})

    def test_create_user_sends_data_center_payload(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"name": "ada"}, method="POST")
        service = JiraService(
            {
                "email": "admin@example.com",
                "api_token": "jira-token",
                "base_url": "https://jira.example.com",
                "deployment": "data_center",
            },
            client=client,
        )

        user = service.create_user(
            "ada@example.com",
            username="ada",
            display_name="Ada",
            products=["jira-software"],
        )

        self.assertEqual(user["name"], "ada")
        self.assertEqual(
            client.request.call_args.args[:2],
            ("POST", "https://jira.example.com/rest/api/2/user"),
        )
        self.assertEqual(
            client.request.call_args.kwargs["json"],
            {"emailAddress": "ada@example.com", "name": "ada", "displayName": "Ada"},
        )

    def test_add_attachment_sends_multipart_payload(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            [{"id": "att-1", "filename": "report.txt"}],
            method="POST",
            url="https://example.atlassian.net/rest/api/3/issue/ENG-1/attachments",
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        attachments = service.add_attachment(
            "ENG-1",
            filename="report.txt",
            content=b"hello",
            mime_type="text/plain",
        )

        self.assertEqual(attachments[0]["id"], "att-1")
        self.assertEqual(
            client.request.call_args.args[:2],
            ("POST", "https://example.atlassian.net/rest/api/3/issue/ENG-1/attachments"),
        )
        self.assertEqual(client.request.call_args.kwargs["files"]["file"][0], "report.txt")
        self.assertEqual(client.request.call_args.kwargs["files"]["file"][1], b"hello")
        self.assertEqual(client.request.call_args.kwargs["files"]["file"][2], "text/plain")
        self.assertEqual(
            client.request.call_args.kwargs["headers"]["X-Atlassian-Token"],
            "no-check",
        )

    def test_list_attachments_reads_issue_attachment_field(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"fields": {"attachment": [{"id": "att-1"}, {"id": "att-2"}]}}
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        result = service.list_attachments("ENG-1", limit=1, start_at=1)

        self.assertEqual(result["attachments"], [{"id": "att-2"}])
        self.assertEqual(result["startAt"], 1)
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["isLast"])
        self.assertEqual(client.request.call_args.kwargs["params"], {"fields": "attachment"})

    def test_transition_issue_refetches_issue(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _response(None, status_code=204, method="POST"),
            _response({"id": "10001", "key": "ENG-1", "fields": {"status": {"name": "Done"}}}),
        ]
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        result = service.transition_issue("ENG-1", "31")

        self.assertEqual(result["transitionId"], "31")
        self.assertEqual(result["issue"]["key"], "ENG-1")

    def test_http_error_detail_is_truncated(self) -> None:
        client = MagicMock()
        request = httpx.Request("GET", "https://example.atlassian.net/rest/api/3/myself")
        client.request.return_value = httpx.Response(
            400,
            content=("x" * 700).encode(),
            request=request,
        )
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        with self.assertRaisesRegex(ValueError, r"\.\.\.$"):
            service.get_myself()

    def test_non_json_response_raises_readable_error(self) -> None:
        client = MagicMock()
        request = httpx.Request("GET", "https://example.atlassian.net/rest/api/3/myself")
        client.request.return_value = httpx.Response(200, content=b"not json", request=request)
        service = JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

        with self.assertRaisesRegex(ValueError, "non-JSON"):
            service.get_myself()


class JiraNodeHandlerTests(unittest.TestCase):
    def test_create_issue_resolves_fields_and_calls_service(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "createIssue",
                "jiraProjectKey": "ENG",
                "jiraIssueType": "Bug",
                "jiraSummary": "$input.title",
                "jiraDescription": "$input.description",
                "jiraLabels": '["automation"]',
            },
            {"title": "Fix checkout", "description": "Checkout is broken"},
        )
        mock_service = MagicMock()
        mock_service.create_issue.return_value = {"id": "10001", "key": "ENG-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.create_issue.assert_called_once_with(
            "ENG",
            "Bug",
            "Fix checkout",
            description="Checkout is broken",
            assignee_account_id=None,
            labels=["automation"],
            issue_type_id=None,
        )
        self.assertEqual(result["key"], "ENG-1")

    def test_rejects_non_jira_credential(self) -> None:
        ctx = _make_ctx(
            {"credentialId": "cred-1", "jiraOperation": "listProjects"},
            credential_type=CredentialType.github,
        )

        with _mock_jira_credential(CredentialType.github):
            with self.assertRaisesRegex(ValueError, "Jira credential"):
                execute(ctx)

    def test_update_issue_propagates_service_validation_error(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "updateIssue",
                "jiraIssueKey": "ENG-1",
            }
        )
        mock_service = MagicMock()
        mock_service.update_issue.side_effect = ValueError(
            "Jira updateIssue requires at least one field to update"
        )

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                with self.assertRaisesRegex(ValueError, "at least one field"):
                    execute(ctx)

        mock_service.update_issue.assert_called_once()

    def test_notify_issue_resolves_payload_fields(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "notifyIssue",
                "jiraIssueKey": "ENG-1",
                "jiraNotifySubject": "$input.subject",
                "jiraNotifyTextBody": "$input.body",
                "jiraNotifyTo": '{"watchers":true}',
            },
            {"subject": "Heads up", "body": "Issue changed"},
        )
        mock_service = MagicMock()
        mock_service.notify_issue.return_value = True

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.notify_issue.assert_called_once_with(
            "ENG-1",
            subject="Heads up",
            text_body="Issue changed",
            html_body=None,
            to={"watchers": True},
        )
        self.assertTrue(result["notified"])

    def test_update_comment_requires_comment_id_and_body(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "updateComment",
                "jiraIssueKey": "ENG-1",
                "jiraCommentId": "10001",
                "jiraCommentBody": "$input.body",
            },
            {"body": "Updated comment"},
        )
        mock_service = MagicMock()
        mock_service.update_comment.return_value = {"id": "10001"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.update_comment.assert_called_once_with("ENG-1", "10001", "Updated comment")
        self.assertEqual(result["comment"]["id"], "10001")

    def test_create_user_parses_product_list(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "createUser",
                "jiraUserEmail": "$input.email",
                "jiraUsername": "$input.username",
                "jiraUserDisplayName": "Ada",
                "jiraUserProducts": '["jira-software"]',
            },
            {"email": "ada@example.com", "username": "ada"},
        )
        mock_service = MagicMock()
        mock_service.create_user.return_value = {"accountId": "acct-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.create_user.assert_called_once_with(
            "ada@example.com",
            username="ada",
            display_name="Ada",
            products=["jira-software"],
        )
        self.assertEqual(result["user"]["accountId"], "acct-1")

    def test_add_attachment_decodes_base64_content(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "addAttachment",
                "jiraIssueKey": "ENG-1",
                "jiraAttachmentFilename": "report.txt",
                "jiraAttachmentBase64": "aGVsbG8=",
                "jiraAttachmentMimeType": "text/plain",
            }
        )
        mock_service = MagicMock()
        mock_service.add_attachment.return_value = [{"id": "att-1"}]

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.add_attachment.assert_called_once_with(
            "ENG-1",
            filename="report.txt",
            content=b"hello",
            mime_type="text/plain",
        )
        self.assertEqual(result["attachments"], [{"id": "att-1"}])

    def test_get_attachment_can_include_binary_content(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "getAttachment",
                "jiraAttachmentId": "att-1",
                "jiraIncludeBinary": True,
            }
        )
        mock_service = MagicMock()
        mock_service.get_attachment.return_value = {
            "id": "att-1",
            "content": "https://example.atlassian.net/secure/attachment/att-1/report.txt",
        }
        mock_service.download_attachment.return_value = b"hello"

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.download_attachment.assert_called_once()
        self.assertEqual(result["attachment"]["content_base64"], "aGVsbG8=")

    def test_get_issue_changelog_returns_values(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "getIssueChangelog",
                "jiraIssueKey": "ENG-1",
            }
        )
        mock_service = MagicMock()
        mock_service.get_issue_changelog.return_value = {
            "values": [{"id": "10001", "items": []}],
            "total": 1,
        }

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["changelog"], [{"id": "10001", "items": []}])

    def test_search_issues_passes_next_page_token_and_fields(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "searchIssues",
                "jiraJql": "$input.jql",
                "jiraNextPageToken": "token-1",
                "jiraFields": '["key","summary"]',
                "jiraLimit": "25",
            },
            {"jql": "project = ENG"},
        )
        mock_service = MagicMock()
        mock_service.search_issues.return_value = {
            "issues": [{"id": "10001", "key": "ENG-1"}],
            "nextPageToken": "token-2",
            "isLast": False,
        }

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.search_issues.assert_called_once_with(
            "project = ENG",
            25,
            next_page_token="token-1",
            start_at=0,
            fields=["key", "summary"],
        )
        self.assertEqual(result["pagination"]["nextPageToken"], "token-2")
        self.assertEqual(result["count"], 1)

    def test_create_issue_uses_issue_type_id_when_provided(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "createIssue",
                "jiraProjectKey": "ENG",
                "jiraIssueType": "Bug",
                "jiraIssueTypeId": "10001",
                "jiraSummary": "Fix checkout",
            }
        )
        mock_service = MagicMock()
        mock_service.create_issue.return_value = {"id": "10001", "key": "ENG-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                execute(ctx)

        mock_service.create_issue.assert_called_once_with(
            "ENG",
            "Bug",
            "Fix checkout",
            description=None,
            assignee_account_id=None,
            labels=None,
            issue_type_id="10001",
        )

    def test_transition_issue_returns_updated_issue(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "transitionIssue",
                "jiraIssueKey": "ENG-1",
                "jiraTransitionId": "31",
            }
        )
        mock_service = MagicMock()
        mock_service.transition_issue.return_value = {
            "transitionId": "31",
            "issue": {"id": "10001", "key": "ENG-1"},
        }

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        self.assertEqual(result["key"], "ENG-1")
        self.assertEqual(result["transition"]["transitionId"], "31")

    def test_get_myself_returns_user(self) -> None:
        ctx = _make_ctx({"credentialId": "cred-1", "jiraOperation": "getMyself"})
        mock_service = MagicMock()
        mock_service.get_myself.return_value = {"accountId": "acct-1", "displayName": "Ada"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.get_myself.assert_called_once_with()
        self.assertEqual(result["user"]["displayName"], "Ada")

    def test_list_projects_returns_projects_and_pagination(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "listProjects",
                "jiraLimit": "25",
                "jiraStartAt": "10",
            }
        )
        mock_service = MagicMock()
        mock_service.list_projects.return_value = {
            "values": [{"id": "10000", "key": "ENG"}],
            "startAt": 10,
            "maxResults": 25,
            "total": 1,
            "isLast": True,
        }

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.list_projects.assert_called_once_with(25, 10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["projects"][0]["key"], "ENG")

    def test_get_issue_returns_issue(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "getIssue",
                "jiraIssueKey": "ENG-1",
            }
        )
        mock_service = MagicMock()
        mock_service.get_issue.return_value = {"id": "10001", "key": "ENG-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.get_issue.assert_called_once_with("ENG-1")
        self.assertEqual(result["key"], "ENG-1")

    def test_delete_issue_returns_deleted_flag(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "deleteIssue",
                "jiraIssueKey": "ENG-1",
            }
        )
        mock_service = MagicMock()
        mock_service.delete_issue.return_value = True

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.delete_issue.assert_called_once_with("ENG-1")
        self.assertTrue(result["deleted"])

    def test_list_comments_returns_comments(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "listComments",
                "jiraIssueKey": "ENG-1",
                "jiraLimit": "25",
                "jiraStartAt": "5",
            }
        )
        mock_service = MagicMock()
        mock_service.list_comments.return_value = {
            "comments": [{"id": "10001", "body": {}}],
            "startAt": 5,
            "maxResults": 25,
            "total": 1,
            "isLast": True,
        }

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.list_comments.assert_called_once_with("ENG-1", 25, 5)
        self.assertEqual(result["count"], 1)

    def test_create_comment_resolves_body(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "createComment",
                "jiraIssueKey": "ENG-1",
                "jiraCommentBody": "$input.body",
            },
            {"body": "New comment"},
        )
        mock_service = MagicMock()
        mock_service.create_comment.return_value = {"id": "10001"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.create_comment.assert_called_once_with("ENG-1", "New comment")
        self.assertEqual(result["comment"]["id"], "10001")

    def test_list_transitions_returns_transitions(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "listTransitions",
                "jiraIssueKey": "ENG-1",
            }
        )
        mock_service = MagicMock()
        mock_service.list_transitions.return_value = [{"id": "31", "name": "Done"}]

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.list_transitions.assert_called_once_with("ENG-1")
        self.assertEqual(result["count"], 1)

    def test_delete_attachment_returns_deleted_flag(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "deleteAttachment",
                "jiraAttachmentId": "att-1",
            }
        )
        mock_service = MagicMock()
        mock_service.delete_attachment.return_value = True

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.delete_attachment.assert_called_once_with("att-1")
        self.assertTrue(result["deleted"])

    def test_get_user_returns_user(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "getUser",
                "jiraAccountId": "acct-1",
            }
        )
        mock_service = MagicMock()
        mock_service.get_user.return_value = {"accountId": "acct-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.get_user.assert_called_once_with("acct-1")
        self.assertEqual(result["user"]["accountId"], "acct-1")

    def test_delete_user_returns_deleted_flag(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "deleteUser",
                "jiraAccountId": "acct-1",
            }
        )
        mock_service = MagicMock()
        mock_service.delete_user.return_value = True

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.delete_user.assert_called_once_with("acct-1")
        self.assertTrue(result["deleted"])

    def test_update_issue_null_expression_clears_assignee(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "updateIssue",
                "jiraIssueKey": "ENG-1",
                "jiraAssigneeAccountId": "null",
            }
        )
        mock_service = MagicMock()
        mock_service.update_issue.return_value = {"id": "10001", "key": "ENG-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.update_issue.assert_called_once()
        self.assertIsNone(mock_service.update_issue.call_args.kwargs["assignee_account_id"])
        self.assertEqual(result["key"], "ENG-1")

    def test_add_attachment_decodes_data_url_content(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "addAttachment",
                "jiraIssueKey": "ENG-1",
                "jiraAttachmentFilename": "report.txt",
                "jiraAttachmentBase64": "data:text/plain;base64,aGVsbG8=",
            }
        )
        mock_service = MagicMock()
        mock_service.add_attachment.return_value = [{"id": "att-1"}]

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                execute(ctx)

        mock_service.add_attachment.assert_called_once_with(
            "ENG-1",
            filename="report.txt",
            content=b"hello",
            mime_type="text/plain",
        )

    def test_list_attachments_can_include_binary_content(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "listAttachments",
                "jiraIssueKey": "ENG-1",
                "jiraIncludeBinary": True,
                "jiraStartAt": "1",
            }
        )
        mock_service = MagicMock()
        mock_service.list_attachments.return_value = {
            "attachments": [
                {
                    "id": "att-2",
                    "content": "https://example.atlassian.net/secure/attachment/att-2/report.txt",
                }
            ],
            "startAt": 1,
            "maxResults": 50,
            "total": 2,
            "isLast": True,
        }
        mock_service.download_attachment.return_value = b"hello"

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                result = execute(ctx)

        mock_service.list_attachments.assert_called_once_with("ENG-1", 50, 1)
        mock_service.download_attachment.assert_called_once()
        self.assertEqual(result["attachments"][0]["content_base64"], "aGVsbG8=")

    def test_create_issue_parses_comma_separated_labels(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "createIssue",
                "jiraProjectKey": "ENG",
                "jiraSummary": "Fix checkout",
                "jiraLabels": "automation, bug",
            }
        )
        mock_service = MagicMock()
        mock_service.create_issue.return_value = {"id": "10001", "key": "ENG-1"}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                execute(ctx)

        mock_service.create_issue.assert_called_once_with(
            "ENG",
            "Task",
            "Fix checkout",
            description=None,
            assignee_account_id=None,
            labels=["automation", "bug"],
            issue_type_id=None,
        )

    def test_search_issues_parses_comma_separated_fields(self) -> None:
        ctx = _make_ctx(
            {
                "credentialId": "cred-1",
                "jiraOperation": "searchIssues",
                "jiraJql": "project = ENG",
                "jiraFields": "key, summary, status",
            }
        )
        mock_service = MagicMock()
        mock_service.search_issues.return_value = {"issues": [], "isLast": True}

        with _mock_jira_credential(CredentialType.jira):
            with patch("app.services.jira_service.JiraService", return_value=mock_service):
                execute(ctx)

        mock_service.search_issues.assert_called_once_with(
            "project = ENG",
            50,
            next_page_token=None,
            start_at=0,
            fields=["key", "summary", "status"],
        )


def _make_ctx(
    node_data: dict,
    inputs: dict | None = None,
    credential_type: CredentialType = CredentialType.jira,
) -> NodeExecutionContext:
    executor = MagicMock()

    def evaluate_message_template(value: str, current_inputs: dict, _node_id: str) -> str:
        if value.startswith("$input."):
            return str(current_inputs.get(value.removeprefix("$input."), ""))
        return value

    executor.evaluate_message_template.side_effect = evaluate_message_template
    executor._get_accessible_credential.return_value = MagicMock(
        encrypted_config="{}",
        type=credential_type,
    )
    return NodeExecutionContext(
        executor=executor,
        node_id="jira-1",
        inputs=inputs or {},
        allow_branch_skip=False,
        start_time=0,
        node={"id": "jira-1", "type": "jira", "data": node_data},
        node_type="jira",
        node_data=node_data,
        node_label="jiraNode",
    )


@contextmanager
def _mock_jira_credential(credential_type: CredentialType) -> Iterator[None]:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter.return_value.first.return_value = MagicMock(
        encrypted_config="{}",
        type=credential_type,
    )
    with patch("app.db.session.SessionLocal", return_value=db):
        with patch(
            "app.services.encryption.decrypt_config",
            return_value={
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
        ):
            yield
