"""Unit tests for GitHubService and the workflow executor GitHub branch."""

import base64
import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.github_service import GitHubService


def _make_config() -> dict[str, str]:
    return {
        "api_key": "ghp_test_token",
        "base_url": "https://api.github.com",
    }


def _make_response(status_code: int, payload: object) -> httpx.Response:
    request = httpx.Request("GET", "https://api.github.com/test")
    return httpx.Response(status_code=status_code, json=payload, request=request)


class GitHubServiceTests(unittest.TestCase):
    def test_get_repository_returns_json(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(200, {"full_name": "octo/repo"})

        service = GitHubService(_make_config(), client=client)
        result = service.get_repository("octo", "repo")

        self.assertEqual(result["full_name"], "octo/repo")
        _, kwargs = client.request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ghp_test_token")

    def test_repository_metadata_actions_use_expected_endpoints(self) -> None:
        encoded = base64.b64encode(b"MIT License").decode("ascii")
        client = MagicMock()
        client.request.side_effect = [
            _make_response(
                200,
                {
                    "license": {"name": "MIT License", "spdx_id": "MIT"},
                    "encoding": "base64",
                    "content": encoded,
                },
            ),
            _make_response(200, {"health_percentage": 95}),
            _make_response(200, [{"path": "/README.md", "count": 20}]),
            _make_response(200, [{"referrer": "google.com", "count": 10}]),
        ]
        service = GitHubService(_make_config(), client=client)

        license_data = service.get_repository_license("octo", "repo")
        profile = service.get_repository_profile("octo", "repo")
        paths = service.list_popular_paths("octo", "repo")
        referrers = service.list_referrers("octo", "repo")

        self.assertEqual(license_data["decoded_content"], "MIT License")
        self.assertEqual(profile["health_percentage"], 95)
        self.assertEqual(paths[0]["path"], "/README.md")
        self.assertEqual(referrers[0]["referrer"], "google.com")
        calls = client.request.call_args_list
        self.assertTrue(calls[0].args[1].endswith("/repos/octo/repo/license"))
        self.assertTrue(calls[1].args[1].endswith("/repos/octo/repo/community/profile"))
        self.assertTrue(calls[2].args[1].endswith("/repos/octo/repo/traffic/popular/paths"))
        self.assertTrue(calls[3].args[1].endswith("/repos/octo/repo/traffic/popular/referrers"))

    def test_create_issue_sends_optional_fields(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(201, {"number": 42, "title": "Bug"})

        service = GitHubService(_make_config(), client=client)
        result = service.create_issue(
            "octo",
            "repo",
            "Bug",
            body="Details",
            labels=["bug"],
            assignees=["monalisa"],
        )

        self.assertEqual(result["number"], 42)
        _, kwargs = client.request.call_args
        self.assertEqual(
            kwargs["json"],
            {
                "title": "Bug",
                "body": "Details",
                "labels": ["bug"],
                "assignees": ["monalisa"],
            },
        )

    def test_list_issues_filters_out_pull_requests(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(
            200,
            [
                {"number": 1, "title": "Issue only"},
                {
                    "number": 2,
                    "title": "Actually a PR",
                    "pull_request": {"url": "https://api.github.com/pulls/2"},
                },
            ],
        )

        service = GitHubService(_make_config(), client=client)
        result = service.list_issues("octo", "repo")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number"], 1)

    def test_repository_issue_and_pull_request_filters_are_forwarded(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _make_response(200, []),
            _make_response(200, []),
        ]
        service = GitHubService(_make_config(), client=client)

        service.list_issues(
            "octo",
            "repo",
            state="all",
            per_page=250,
            assignee="monalisa",
            creator="octocat",
            mentioned="hubot",
            labels="bug,backend",
            since="2026-01-01T00:00:00Z",
            sort="updated",
            direction="asc",
        )
        service.list_pull_requests(
            "octo",
            "repo",
            state="closed",
            per_page=50,
            sort="popularity",
            direction="desc",
        )

        issue_call, pull_call = client.request.call_args_list
        self.assertEqual(
            issue_call.kwargs["params"],
            {
                "state": "all",
                "per_page": 100,
                "assignee": "monalisa",
                "creator": "octocat",
                "mentioned": "hubot",
                "labels": "bug,backend",
                "since": "2026-01-01T00:00:00Z",
                "sort": "updated",
                "direction": "asc",
            },
        )
        self.assertEqual(
            pull_call.kwargs["params"],
            {
                "state": "closed",
                "per_page": 50,
                "sort": "popularity",
                "direction": "desc",
            },
        )

    def test_update_issue_sends_edit_fields(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(
            200,
            {"number": 42, "title": "Updated", "state": "closed"},
        )

        service = GitHubService(_make_config(), client=client)
        result = service.update_issue(
            "octo",
            "repo",
            42,
            title="Updated",
            body="Done",
            state="closed",
            state_reason="completed",
            labels=[],
            assignees=["monalisa"],
        )

        self.assertEqual(result["state"], "closed")
        method, url = client.request.call_args.args
        self.assertEqual(method, "PATCH")
        self.assertTrue(url.endswith("/repos/octo/repo/issues/42"))
        kwargs = client.request.call_args.kwargs
        self.assertEqual(
            kwargs["json"],
            {
                "title": "Updated",
                "body": "Done",
                "state": "closed",
                "state_reason": "completed",
                "labels": [],
                "assignees": ["monalisa"],
            },
        )

    def test_lock_issue_sends_lock_reason(self) -> None:
        client = MagicMock()
        request = httpx.Request("PUT", "https://api.github.com/test")
        client.request.return_value = httpx.Response(status_code=204, request=request)

        service = GitHubService(_make_config(), client=client)
        result = service.lock_issue("octo", "repo", 42, lock_reason="resolved")

        self.assertEqual(
            result,
            {"issue_number": 42, "locked": True, "lock_reason": "resolved"},
        )
        method, url = client.request.call_args.args
        self.assertEqual(method, "PUT")
        self.assertTrue(url.endswith("/repos/octo/repo/issues/42/lock"))
        self.assertEqual(client.request.call_args.kwargs["json"], {"lock_reason": "resolved"})

    def test_create_review_sends_event_body_and_commit(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(
            200,
            {"id": 77, "state": "CHANGES_REQUESTED"},
        )

        service = GitHubService(_make_config(), client=client)
        result = service.create_review(
            "octo",
            "repo",
            42,
            "REQUEST_CHANGES",
            body="Please add tests",
            commit_id="abc123",
        )

        self.assertEqual(result["id"], 77)
        method, url = client.request.call_args.args
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/repos/octo/repo/pulls/42/reviews"))
        self.assertEqual(
            client.request.call_args.kwargs["json"],
            {
                "event": "REQUEST_CHANGES",
                "body": "Please add tests",
                "commit_id": "abc123",
            },
        )

    def test_get_list_and_update_review_use_review_endpoints(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _make_response(200, {"id": 77}),
            _make_response(200, [{"id": 77}, {"id": 78}]),
            _make_response(200, {"id": 77, "body": "Updated"}),
        ]
        service = GitHubService(_make_config(), client=client)

        review = service.get_review("octo", "repo", 42, 77)
        reviews = service.list_reviews("octo", "repo", 42, per_page=250)
        updated = service.update_review("octo", "repo", 42, 77, "Updated")

        self.assertEqual(review["id"], 77)
        self.assertEqual(len(reviews), 2)
        self.assertEqual(updated["body"], "Updated")
        first_call, second_call, third_call = client.request.call_args_list
        self.assertEqual(first_call.args[0], "GET")
        self.assertTrue(first_call.args[1].endswith("/pulls/42/reviews/77"))
        self.assertEqual(second_call.kwargs["params"], {"per_page": 100})
        self.assertEqual(third_call.args[0], "PUT")
        self.assertEqual(third_call.kwargs["json"], {"body": "Updated"})

    def test_get_file_decodes_base64(self) -> None:
        encoded = base64.b64encode("hello".encode("utf-8")).decode("ascii")
        client = MagicMock()
        client.request.return_value = _make_response(
            200,
            {
                "name": "README.md",
                "path": "README.md",
                "sha": "abc123",
                "encoding": "base64",
                "content": encoded,
                "html_url": "https://github.com/octo/repo/blob/main/README.md",
            },
        )

        service = GitHubService(_make_config(), client=client)
        result = service.get_file("octo", "repo", "README.md")

        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["sha"], "abc123")

    def test_upsert_file_reuses_existing_sha_when_available(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _make_response(200, {"sha": "existing-sha"}),
            _make_response(
                200,
                {
                    "content": {"path": "README.md", "sha": "new-sha"},
                    "commit": {"sha": "commit-sha"},
                },
            ),
        ]

        service = GitHubService(_make_config(), client=client)
        result = service.upsert_file(
            "octo",
            "repo",
            "README.md",
            "Update README",
            "Hello world",
            branch="main",
        )

        self.assertEqual(result["sha"], "new-sha")
        _, kwargs = client.request.call_args
        self.assertEqual(kwargs["json"]["sha"], "existing-sha")
        self.assertIn("content", kwargs["json"])

    def test_delete_file_fetches_sha_before_delete(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _make_response(200, {"sha": "existing-sha"}),
            _make_response(200, {"commit": {"sha": "commit-sha"}}),
        ]

        service = GitHubService(_make_config(), client=client)
        result = service.delete_file(
            "octo",
            "repo",
            "README.md",
            "Remove README",
            branch="main",
        )

        self.assertTrue(result["deleted"])
        _, kwargs = client.request.call_args
        self.assertEqual(kwargs["json"]["sha"], "existing-sha")
        self.assertEqual(kwargs["json"]["message"], "Remove README")

    def test_create_release_sends_release_payload(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(201, {"id": 7, "tag_name": "v1.2.3"})

        service = GitHubService(_make_config(), client=client)
        result = service.create_release(
            "octo",
            "repo",
            "v1.2.3",
            name="Version 1.2.3",
            body="Release notes",
            target_commitish="main",
            draft=True,
            prerelease=False,
        )

        self.assertEqual(result["id"], 7)
        _, kwargs = client.request.call_args
        self.assertEqual(
            kwargs["json"],
            {
                "tag_name": "v1.2.3",
                "name": "Version 1.2.3",
                "body": "Release notes",
                "target_commitish": "main",
                "draft": True,
                "prerelease": False,
            },
        )

    def test_dispatch_workflow_accepts_no_content_response(self) -> None:
        client = MagicMock()
        request = httpx.Request("POST", "https://api.github.com/test")
        client.request.return_value = httpx.Response(status_code=204, request=request)

        service = GitHubService(_make_config(), client=client)
        result = service.dispatch_workflow(
            "octo",
            "repo",
            "build.yml",
            "main",
            inputs={"environment": "prod"},
        )

        self.assertTrue(result["dispatched"])
        _, kwargs = client.request.call_args
        self.assertEqual(kwargs["json"]["ref"], "main")
        self.assertEqual(kwargs["json"]["inputs"], {"environment": "prod"})

    def test_dispatch_workflow_returns_run_details_from_created_response(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(
            200,
            {
                "workflow_run_id": 123,
                "run_url": "https://api.github.com/repos/octo/repo/actions/runs/123",
                "html_url": "https://github.com/octo/repo/actions/runs/123",
            },
        )

        service = GitHubService(_make_config(), client=client)
        result = service.dispatch_workflow("octo", "repo", "build.yml", "main")

        self.assertTrue(result["dispatched"])
        self.assertEqual(result["workflow_run_id"], 123)
        self.assertEqual(result["ref"], "main")

    def test_enable_disable_and_usage_workflow_endpoints(self) -> None:
        client = MagicMock()
        request = httpx.Request("PUT", "https://api.github.com/test")
        client.request.side_effect = [
            httpx.Response(status_code=204, request=request),
            httpx.Response(status_code=204, request=request),
            _make_response(200, {"billable": {"UBUNTU": {"total_ms": 1200}}}),
        ]

        service = GitHubService(_make_config(), client=client)
        enabled = service.enable_workflow("octo", "repo", "build.yml")
        disabled = service.disable_workflow("octo", "repo", "build.yml")
        usage = service.get_workflow_usage("octo", "repo", "build.yml")

        self.assertTrue(enabled["enabled"])
        self.assertTrue(disabled["disabled"])
        self.assertEqual(usage["billable"]["UBUNTU"]["total_ms"], 1200)
        enable_call, disable_call, usage_call = client.request.call_args_list
        self.assertTrue(enable_call.args[1].endswith("/actions/workflows/build.yml/enable"))
        self.assertTrue(disable_call.args[1].endswith("/actions/workflows/build.yml/disable"))
        self.assertTrue(usage_call.args[1].endswith("/actions/workflows/build.yml/timing"))

    def test_dispatch_workflow_and_wait_returns_completed_run(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _make_response(200, {"workflow_run_id": 123}),
            _make_response(
                200,
                {"id": 123, "status": "completed", "conclusion": "success"},
            ),
        ]
        service = GitHubService(_make_config(), client=client)

        result = service.dispatch_workflow_and_wait(
            "octo",
            "repo",
            "build.yml",
            "main",
            timeout_seconds=10,
            poll_interval_seconds=0.1,
        )

        self.assertTrue(result["completed"])
        self.assertEqual(result["conclusion"], "success")
        self.assertEqual(result["workflow_run"]["id"], 123)

    def test_dispatch_workflow_and_wait_discovers_run_after_no_content_response(self) -> None:
        client = MagicMock()
        request = httpx.Request("POST", "https://api.github.com/test")
        client.request.side_effect = [
            httpx.Response(status_code=204, request=request),
            _make_response(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 456,
                            "event": "workflow_dispatch",
                            "head_branch": "main",
                            "created_at": "2099-01-01T00:00:00Z",
                            "status": "queued",
                        }
                    ]
                },
            ),
            _make_response(
                200,
                {"id": 456, "status": "completed", "conclusion": "success"},
            ),
        ]
        service = GitHubService(_make_config(), client=client)

        result = service.dispatch_workflow_and_wait(
            "octo",
            "repo",
            "build.yml",
            "main",
            timeout_seconds=10,
            poll_interval_seconds=0.1,
        )

        self.assertTrue(result["completed"])
        self.assertEqual(result["workflow_run_id"], 456)
        self.assertEqual(result["workflow_run"]["id"], 456)
        discovery_call = client.request.call_args_list[1]
        self.assertTrue(discovery_call.args[1].endswith("/actions/workflows/build.yml/runs"))
        self.assertEqual(
            discovery_call.kwargs["params"],
            {"event": "workflow_dispatch", "per_page": 100},
        )

    def test_user_actions_use_expected_endpoints(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _make_response(200, [{"name": "repo"}]),
            _make_response(200, [{"number": 1}]),
            _make_response(201, {"id": 9, "email": "user@example.com"}),
        ]
        service = GitHubService(_make_config(), client=client)

        repositories = service.get_user_repositories("octocat", per_page=50)
        issues = service.get_user_issues(
            state="all",
            per_page=50,
            mentioned="hubot",
            labels="bug",
            sort="updated",
            direction="asc",
        )
        invitation = service.invite_user("octo-org", "user@example.com")

        self.assertEqual(repositories[0]["name"], "repo")
        self.assertEqual(issues[0]["number"], 1)
        self.assertEqual(invitation["id"], 9)
        calls = client.request.call_args_list
        self.assertTrue(calls[0].args[1].endswith("/users/octocat/repos"))
        self.assertTrue(calls[1].args[1].endswith("/issues"))
        self.assertEqual(calls[1].kwargs["params"]["filter"], "mentioned")
        self.assertNotIn("mentioned", calls[1].kwargs["params"])
        self.assertTrue(calls[2].args[1].endswith("/orgs/octo-org/invitations"))

    def test_update_release_includes_false_boolean_fields(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(200, {"id": 7, "tag_name": "v1.2.4"})

        service = GitHubService(_make_config(), client=client)
        result = service.update_release(
            "octo",
            "repo",
            7,
            name="",
            body="",
            draft=False,
            prerelease=False,
        )

        self.assertEqual(result["id"], 7)
        _, kwargs = client.request.call_args
        self.assertEqual(
            kwargs["json"],
            {
                "name": "",
                "body": "",
                "draft": False,
                "prerelease": False,
            },
        )

    def test_request_raises_value_error_on_api_error(self) -> None:
        client = MagicMock()
        client.request.return_value = _make_response(404, {"message": "Not Found"})

        service = GitHubService(_make_config(), client=client)

        with self.assertRaises(ValueError) as ctx:
            service.get_repository("octo", "missing")

        self.assertIn("GitHub API error", str(ctx.exception))


def _make_github_workflow(github_data: dict) -> tuple[list[dict], list[dict], dict]:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "github",
            "type": "github",
            "position": {"x": 200, "y": 0},
            "data": {"label": "githubNode", **github_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$githubNode", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "github"},
        {"id": "e2", "source": "github", "target": "out"},
    ]
    return nodes, edges, {"text": "hello"}


class GitHubExecutorBranchTests(unittest.TestCase):
    def test_missing_credential_results_in_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "",
                "githubOperation": "getRepository",
                "githubOwner": "octo",
                "githubRepo": "repo",
            }
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        github_result = next(
            (r for r in result.node_results if r["node_label"] == "githubNode"), None
        )
        self.assertIsNotNone(github_result)
        self.assertIn("credential", github_result.get("error", "").lower())

    def test_get_repository_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "getRepository",
                "githubOwner": "octo",
                "githubRepo": "repo",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.get_repository",
                    return_value={"full_name": "octo/repo"},
                ) as mock_get_repo:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_get_repo.assert_called_once_with("octo", "repo")
        self.assertEqual(result.status, "success")

    def test_get_repository_profile_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "getRepositoryProfile",
                "githubOwner": "octo",
                "githubRepo": "repo",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.get_repository_profile",
                    return_value={"health_percentage": 95},
                ) as mock_profile:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_profile.assert_called_once_with("octo", "repo")
        self.assertEqual(result.status, "success")

    def test_list_issues_operation_forwards_repository_filters(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "listIssues",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubState": "all",
                "githubPerPage": "50",
                "githubAssignee": "monalisa",
                "githubCreator": "octocat",
                "githubMentioned": "hubot",
                "githubLabelsFilter": "bug,backend",
                "githubSince": "2026-01-01T00:00:00Z",
                "githubSort": "updated",
                "githubDirection": "asc",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.list_issues",
                    return_value=[],
                ) as mock_list_issues:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_list_issues.assert_called_once_with(
            "octo",
            "repo",
            state="all",
            per_page=50,
            assignee="monalisa",
            creator="octocat",
            mentioned="hubot",
            labels="bug,backend",
            since="2026-01-01T00:00:00Z",
            sort="updated",
            direction="asc",
        )
        self.assertEqual(result.status, "success")

    def test_create_issue_operation_parses_json_arrays(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "createIssue",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubTitle": "Bug report",
                "githubBody": "$input.text",
                "githubLabels": '["bug", "triage"]',
                "githubAssignees": '["monalisa"]',
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.create_issue",
                    return_value={"number": 9, "title": "Bug report"},
                ) as mock_create_issue:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_create_issue.assert_called_once_with(
            "octo",
            "repo",
            "Bug report",
            body="hello",
            labels=["bug", "triage"],
            assignees=["monalisa"],
        )
        self.assertEqual(result.status, "success")

    def test_invalid_labels_json_results_in_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "createIssue",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubTitle": "Bug report",
                "githubLabels": "{bad json",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
                result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        github_result = next(
            (r for r in result.node_results if r["node_label"] == "githubNode"), None
        )
        self.assertIsNotNone(github_result)
        self.assertIn("labels", github_result.get("error", "").lower())

    def test_create_comment_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "createComment",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubIssueNumber": "14",
                "githubCommentBody": "$input.text",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.create_issue_comment",
                    return_value={"id": 88, "html_url": "https://github.com/comment"},
                ) as mock_create_comment:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_create_comment.assert_called_once_with("octo", "repo", 14, "hello")
        self.assertEqual(result.status, "success")

    def test_list_organization_repositories_does_not_require_repo(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "listOrganizationRepositories",
                "githubOwner": "octo-org",
                "githubRepo": "",
                "githubPerPage": "50",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.list_organization_repositories",
                    return_value=[{"full_name": "octo-org/repo"}],
                ) as mock_list_repos:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_list_repos.assert_called_once_with("octo-org", per_page=50)
        self.assertEqual(result.status, "success")

    def test_dispatch_workflow_parses_inputs_json(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "dispatchWorkflow",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubWorkflowId": "build.yml",
                "githubBranch": "main",
                "githubWorkflowInputs": '{"environment":"prod"}',
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.dispatch_workflow",
                    return_value={"dispatched": True, "workflow_id": "build.yml"},
                ) as mock_dispatch:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_dispatch.assert_called_once_with(
            "octo",
            "repo",
            "build.yml",
            "main",
            inputs={"environment": "prod"},
        )
        self.assertEqual(result.status, "success")

    def test_enable_workflow_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "enableWorkflow",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubWorkflowId": "build.yml",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.enable_workflow",
                    return_value={"workflow_id": "build.yml", "enabled": True},
                ) as mock_enable:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_enable.assert_called_once_with("octo", "repo", "build.yml")
        self.assertEqual(result.status, "success")

    def test_get_workflow_usage_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "getWorkflowUsage",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubWorkflowId": "build.yml",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.get_workflow_usage",
                    return_value={"billable": {"UBUNTU": {"total_ms": 1200}}},
                ) as mock_usage:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_usage.assert_called_once_with("octo", "repo", "build.yml")
        self.assertEqual(result.status, "success")

    def test_dispatch_workflow_and_wait_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "dispatchWorkflowAndWait",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubWorkflowId": "build.yml",
                "githubBranch": "main",
                "githubWorkflowInputs": '{"environment":"prod"}',
                "githubWaitTimeoutSeconds": "120",
                "githubPollIntervalSeconds": "2",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.dispatch_workflow_and_wait",
                    return_value={"completed": True, "conclusion": "success"},
                ) as mock_wait:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_wait.assert_called_once_with(
            "octo",
            "repo",
            "build.yml",
            "main",
            inputs={"environment": "prod"},
            timeout_seconds=120,
            poll_interval_seconds=2.0,
        )
        self.assertEqual(result.status, "success")

    def test_invite_user_operation_calls_service_without_owner_or_repo(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "inviteUser",
                "githubOwner": "",
                "githubRepo": "",
                "githubOrganization": "octo-org",
                "githubInviteEmail": "user@example.com",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.invite_user",
                    return_value={"id": 9, "email": "user@example.com"},
                ) as mock_invite:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_invite.assert_called_once_with("octo-org", "user@example.com")
        self.assertEqual(result.status, "success")

    def test_get_user_issues_operation_calls_service_without_owner_or_repo(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "getUserIssues",
                "githubOwner": "",
                "githubRepo": "",
                "githubState": "all",
                "githubPerPage": "50",
                "githubMentioned": "hubot",
                "githubLabelsFilter": "bug",
                "githubSort": "updated",
                "githubDirection": "asc",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.get_user_issues",
                    return_value=[],
                ) as mock_issues:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_issues.assert_called_once_with(
            state="all",
            per_page=50,
            mentioned="hubot",
            labels="bug",
            since=None,
            sort="updated",
            direction="asc",
        )
        self.assertEqual(result.status, "success")

    def test_n8n_compatible_repository_and_user_alias_actions_call_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        cases = [
            (
                "getRepositoryIssues",
                "get_repository_issues",
                {
                    "githubOwner": "octo",
                    "githubRepo": "repo",
                    "githubState": "open",
                    "githubPerPage": "30",
                },
            ),
            (
                "getRepositoryPullRequests",
                "get_repository_pull_requests",
                {
                    "githubOwner": "octo",
                    "githubRepo": "repo",
                    "githubState": "open",
                    "githubPerPage": "30",
                },
            ),
            (
                "getUserRepositories",
                "get_user_repositories",
                {
                    "githubOwner": "octocat",
                    "githubRepo": "",
                    "githubPerPage": "30",
                },
            ),
        ]

        for operation, method_name, operation_data in cases:
            with self.subTest(operation=operation):
                nodes, edges, inputs = _make_github_workflow(
                    {
                        "credentialId": "cred-1",
                        "githubOperation": operation,
                        **operation_data,
                    }
                )
                with patch("app.db.session.SessionLocal") as mock_session:
                    mock_db = MagicMock()
                    mock_db.__enter__ = MagicMock(return_value=mock_db)
                    mock_db.__exit__ = MagicMock(return_value=False)
                    mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                        encrypted_config="{}",
                        type=CredentialType.github,
                    )
                    mock_session.return_value = mock_db

                    with (
                        patch(
                            "app.services.encryption.decrypt_config",
                            return_value=_make_config(),
                        ),
                        patch(
                            f"app.services.github_service.GitHubService.{method_name}",
                            return_value=[],
                        ) as mock_method,
                    ):
                        executor = WorkflowExecutor(
                            nodes=nodes,
                            edges=edges,
                            actor_user_id=uuid.uuid4(),
                        )
                        result = executor.execute(
                            workflow_id=uuid.uuid4(),
                            initial_inputs=inputs,
                        )

                mock_method.assert_called_once()
                self.assertEqual(result.status, "success")

    def test_invalid_credential_type_results_in_error(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "getRepository",
                "githubOwner": "octo",
                "githubRepo": "repo",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.custom,
            )
            mock_session.return_value = mock_db

            executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        github_result = next(
            (r for r in result.node_results if r["node_label"] == "githubNode"), None
        )
        self.assertIsNotNone(github_result)
        self.assertIn("github credential", github_result.get("error", "").lower())

    def test_update_issue_can_clear_labels_and_assignees(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "updateIssue",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubIssueNumber": "14",
                "githubLabels": "[]",
                "githubAssignees": "[]",
                "githubState": "closed",
                "githubStateReason": "completed",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.update_issue",
                    return_value={"number": 14, "title": "Issue"},
                ) as mock_update_issue:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_update_issue.assert_called_once_with(
            "octo",
            "repo",
            14,
            title=None,
            body=None,
            state="closed",
            state_reason="completed",
            labels=[],
            assignees=[],
        )
        self.assertEqual(result.status, "success")

    def test_lock_issue_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "lockIssue",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubIssueNumber": "14",
                "githubLockReason": "resolved",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.lock_issue",
                    return_value={
                        "issue_number": 14,
                        "locked": True,
                        "lock_reason": "resolved",
                    },
                ) as mock_lock_issue:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_lock_issue.assert_called_once_with(
            "octo",
            "repo",
            14,
            lock_reason="resolved",
        )
        self.assertEqual(result.status, "success")

    def test_lock_issue_rejects_invalid_reason(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "lockIssue",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubIssueNumber": "14",
                "githubLockReason": "invalid",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
                result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        github_result = next(
            (item for item in result.node_results if item["node_label"] == "githubNode"),
            None,
        )
        self.assertIsNotNone(github_result)
        self.assertIn("lock reason", github_result.get("error", "").lower())

    def test_create_review_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "createReview",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubPullRequestNumber": "14",
                "githubReviewEvent": "REQUEST_CHANGES",
                "githubReviewBody": "Please fix $input.text",
                "githubCommitId": "abc123",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.create_review",
                    return_value={"id": 77, "state": "CHANGES_REQUESTED"},
                ) as mock_create_review:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_create_review.assert_called_once_with(
            "octo",
            "repo",
            14,
            "REQUEST_CHANGES",
            body="Please fix hello",
            commit_id="abc123",
        )
        self.assertEqual(result.status, "success")

    def test_list_reviews_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "listReviews",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubPullRequestNumber": "14",
                "githubPerPage": "50",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.list_reviews",
                    return_value=[{"id": 77}],
                ) as mock_list_reviews:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_list_reviews.assert_called_once_with("octo", "repo", 14, per_page=50)
        self.assertEqual(result.status, "success")

    def test_get_review_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "getReview",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubPullRequestNumber": "14",
                "githubReviewId": "77",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.get_review",
                    return_value={"id": 77, "state": "APPROVED"},
                ) as mock_get_review:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_get_review.assert_called_once_with("octo", "repo", 14, 77)
        self.assertEqual(result.status, "success")

    def test_update_review_operation_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "updateReview",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubPullRequestNumber": "14",
                "githubReviewId": "77",
                "githubReviewBody": "Updated for $input.text",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.update_review",
                    return_value={"id": 77, "body": "Updated for hello"},
                ) as mock_update_review:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_update_review.assert_called_once_with(
            "octo",
            "repo",
            14,
            77,
            "Updated for hello",
        )
        self.assertEqual(result.status, "success")

    def test_create_review_requires_body_for_comment(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "createReview",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubPullRequestNumber": "14",
                "githubReviewEvent": "COMMENT",
                "githubReviewBody": "",
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
                result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        github_result = next(
            (item for item in result.node_results if item["node_label"] == "githubNode"),
            None,
        )
        self.assertIsNotNone(github_result)
        self.assertIn("requires a body", github_result.get("error", "").lower())

    def test_update_release_passes_false_booleans_and_empty_body(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_github_workflow(
            {
                "credentialId": "cred-1",
                "githubOperation": "updateRelease",
                "githubOwner": "octo",
                "githubRepo": "repo",
                "githubReleaseId": "7",
                "githubTagName": "v1.2.4",
                "githubTitle": "",
                "githubBody": "",
                "githubDraft": False,
                "githubPrerelease": False,
            }
        )

        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.github,
            )
            mock_session.return_value = mock_db

            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.github_service.GitHubService.update_release",
                    return_value={"id": 7, "tag_name": "v1.2.4"},
                ) as mock_update_release:
                    executor = WorkflowExecutor(
                        nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()
                    )
                    result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        mock_update_release.assert_called_once_with(
            "octo",
            "repo",
            7,
            tag_name="v1.2.4",
            name="",
            body="",
            target_commitish=None,
            draft=False,
            prerelease=False,
        )
        self.assertEqual(result.status, "success")
