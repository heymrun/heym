"""Regression tests for user-controlled URL path segments in REST integrations.

Jira issue keys, GitHub owners and repository paths, and Grist document and
table IDs are all workflow-controlled values interpolated into a request path.
Both httpx and :func:`urllib.parse.urljoin` apply RFC 3986 dot-segment removal,
so a raw ``../`` in one of them silently retargets the request at a different
endpoint of the same host, under the credential's own authorization.
"""

import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.services.github_service import GitHubService
from app.services.http_paths import encode_path_segment
from app.services.jira_service import JiraService
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.grist_node import execute as grist_execute
from app.services.sentry_service import SentryService

_TRAVERSAL = "../../../../admin/secrets"


def _response(payload: object, url: str = "https://example.test/") -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


class PathSegmentEncodingTests(unittest.TestCase):
    """The shared helper is the single implementation for every client."""

    def test_reserved_characters_and_slashes_are_encoded(self) -> None:
        self.assertEqual(encode_path_segment("a/b"), "a%2Fb")
        self.assertEqual(encode_path_segment("PROJ-1?x=1#y"), "PROJ-1%3Fx%3D1%23y")
        self.assertEqual(encode_path_segment("a b"), "a%20b")

    def test_dot_segments_are_escaped_rather_than_left_resolvable(self) -> None:
        # quote(value, safe="") alone returns these unchanged: "." is always safe.
        self.assertEqual(encode_path_segment(".."), "%2E%2E")
        self.assertEqual(encode_path_segment("."), "%2E")
        self.assertEqual(encode_path_segment("..foo"), "..foo")

    def test_non_string_values_are_accepted(self) -> None:
        self.assertEqual(encode_path_segment(42), "42")


class JiraPathSegmentTests(unittest.TestCase):
    def _service(self, client: MagicMock) -> JiraService:
        return JiraService(
            {
                "email": "ada@example.com",
                "api_token": "jira-token",
                "base_url": "https://example.atlassian.net",
            },
            client=client,
        )

    def test_issue_key_traversal_cannot_leave_the_rest_api_prefix(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"key": "PROJ-1"})

        self._service(client).get_issue(_TRAVERSAL)

        url = client.request.call_args.args[1]
        self.assertTrue(url.startswith("https://example.atlassian.net/rest/api/3/issue/"))
        self.assertNotIn("/admin/secrets", url)
        self.assertIn("%2F", url)

    def test_comment_id_is_encoded_too(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"id": "1"})

        self._service(client).get_comment("PROJ-1", _TRAVERSAL)

        url = client.request.call_args.args[1]
        self.assertTrue(
            url.startswith("https://example.atlassian.net/rest/api/3/issue/PROJ-1/comment/")
        )
        self.assertNotIn("/admin/secrets", url)

    def test_attachment_id_is_encoded(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"id": "1"})

        self._service(client).get_attachment(_TRAVERSAL)

        url = client.request.call_args.args[1]
        self.assertTrue(url.startswith("https://example.atlassian.net/rest/api/3/attachment/"))
        self.assertNotIn("/admin/secrets", url)

    def test_a_bare_dot_dot_issue_key_stays_inside_the_issue_endpoint(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"key": "x"})

        self._service(client).get_issue("..")

        self.assertEqual(
            client.request.call_args.args[1],
            "https://example.atlassian.net/rest/api/3/issue/%2E%2E",
        )

    def test_ordinary_issue_keys_are_unchanged(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"key": "PROJ-42"})

        self._service(client).get_issue("PROJ-42")

        self.assertEqual(
            client.request.call_args.args[1],
            "https://example.atlassian.net/rest/api/3/issue/PROJ-42",
        )


class GitHubPathSegmentTests(unittest.TestCase):
    def _service(self, client: MagicMock) -> GitHubService:
        return GitHubService({"token": "gh-token"}, client=client)

    def test_owner_traversal_cannot_retarget_the_repos_endpoint(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"full_name": "o/r"})

        self._service(client).get_repository(_TRAVERSAL, "repo")

        url = client.request.call_args.args[1]
        self.assertTrue(url.startswith("https://api.github.com/repos/"))
        self.assertNotIn("/admin/secrets", url)

    def test_workflow_id_is_encoded(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"id": 1})

        self._service(client).get_workflow("octo", "repo", _TRAVERSAL)

        url = client.request.call_args.args[1]
        self.assertTrue(url.startswith("https://api.github.com/repos/octo/repo/actions/workflows/"))
        self.assertNotIn("/admin/secrets", url)

    def test_release_tag_is_still_encoded_after_moving_to_the_shared_helper(self) -> None:
        client = MagicMock()
        client.request.return_value = _response({"id": 1})

        self._service(client).get_release_by_tag("octo", "repo", "v1.0/../../x")

        self.assertEqual(
            client.request.call_args.args[1],
            "https://api.github.com/repos/octo/repo/releases/tags/v1.0%2F..%2F..%2Fx",
        )

    def test_content_path_keeps_its_slashes_but_escapes_dot_segments(self) -> None:
        self.assertEqual(GitHubService._encode_content_path("/src/app/main.py"), "src/app/main.py")
        self.assertEqual(
            GitHubService._encode_content_path("../../etc/passwd"),
            "%2E%2E/%2E%2E/etc/passwd",
        )
        self.assertEqual(GitHubService._encode_content_path("a dir/b?c"), "a%20dir/b%3Fc")

    def test_get_file_path_traversal_stays_under_the_contents_endpoint(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            {"type": "file", "encoding": "base64", "content": "", "sha": "s", "path": "p"}
        )

        self._service(client).get_file("octo", "repo", "../../../../settings")

        url = client.request.call_args.args[1]
        self.assertTrue(url.startswith("https://api.github.com/repos/octo/repo/contents/"))
        self.assertNotIn("/settings", url.split("/contents/")[0])
        self.assertIn("%2E%2E", url)

    def test_organization_and_username_are_encoded(self) -> None:
        client = MagicMock()
        client.request.return_value = _response([])
        service = self._service(client)

        service.list_organization_repositories(_TRAVERSAL)
        self.assertTrue(client.request.call_args.args[1].startswith("https://api.github.com/orgs/"))

        service.list_user_repositories(_TRAVERSAL)
        self.assertTrue(
            client.request.call_args.args[1].startswith("https://api.github.com/users/")
        )


class SentryPathSegmentTests(unittest.TestCase):
    def test_a_bare_dot_dot_slug_no_longer_survives_encoding(self) -> None:
        self.assertEqual(SentryService._path_segment(".."), "%2E%2E")
        self.assertEqual(SentryService._path_segment("my-org"), "my-org")
        self.assertEqual(SentryService._path_segment("a/b"), "a%2Fb")


class GristPathSegmentTests(unittest.TestCase):
    def _run(self, doc_id: str, table_id: str) -> str:
        executor = MagicMock()
        executor.evaluate_message_template.side_effect = lambda value, *_args, **_kw: value
        client = MagicMock()
        client.get.return_value = _response({"records": []})

        node_data = {
            "credentialId": "cred-1",
            "gristOperation": "getRecords",
            "gristDocId": doc_id,
            "gristTableId": table_id,
        }
        ctx = NodeExecutionContext(
            executor=executor,
            node_id="n1",
            inputs={},
            allow_branch_skip=False,
            start_time=0.0,
            node={"id": "n1", "type": "grist", "data": node_data},
            node_type="grist",
            node_data=node_data,
            node_label="grist",
        )

        with (
            patch("app.db.session.SessionLocal", MagicMock()),
            patch("app.services.grist_pool.get_grist_client", return_value=client),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={
                    "api_key": "grist-key",
                    "server_url": "https://grist.example.com",
                },
            ),
        ):
            grist_execute(ctx)

        return client.get.call_args.args[0]

    def test_document_and_table_ids_cannot_retarget_the_api(self) -> None:
        path = self._run(_TRAVERSAL, "Table1")
        self.assertTrue(path.startswith("/api/docs/"))
        self.assertNotIn("/admin/secrets", path)

        path = self._run("doc1", _TRAVERSAL)
        self.assertTrue(path.startswith("/api/docs/doc1/tables/"))
        self.assertNotIn("/admin/secrets", path)

    def test_ordinary_ids_are_unchanged(self) -> None:
        self.assertEqual(
            self._run("abc123", "Table1"),
            "/api/docs/abc123/tables/Table1/records",
        )


if __name__ == "__main__":
    unittest.main()
