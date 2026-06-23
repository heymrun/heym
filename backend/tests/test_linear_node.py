"""Unit tests for LinearService and the workflow executor Linear branch."""

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.linear_service import LINEAR_GRAPHQL_URL, LinearService


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", LINEAR_GRAPHQL_URL)
    return httpx.Response(status_code=status_code, json=payload, request=request)


class LinearServiceTests(unittest.TestCase):
    def test_get_viewer_sends_api_key_and_returns_user(self) -> None:
        client = MagicMock()
        client.post.return_value = _response({"data": {"viewer": {"id": "user-1", "name": "Ada"}}})
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        result = service.get_viewer()

        self.assertEqual(result["name"], "Ada")
        self.assertEqual(client.post.call_args.kwargs["headers"]["Authorization"], "lin_api_test")

    def test_list_issues_builds_optional_filters_and_clamps_limit(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {"data": {"issues": {"nodes": [{"id": "issue-1", "identifier": "ENG-1"}]}}}
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        issues = service.list_issues(999, team_id="team-1", project_id="project-1")

        self.assertEqual(issues[0]["identifier"], "ENG-1")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(
            payload["variables"],
            {"first": 250, "teamId": "team-1", "projectId": "project-1"},
        )
        self.assertIn("team: { id: { eq: $teamId } }", payload["query"])
        self.assertIn("project: { id: { eq: $projectId } }", payload["query"])

    def test_create_issue_sends_only_provided_optional_fields(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {"id": "issue-1", "identifier": "ENG-1"},
                    }
                }
            }
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        issue = service.create_issue(
            "team-1",
            "Fix it",
            project_id="project-1",
            priority=2,
        )

        self.assertEqual(issue["identifier"], "ENG-1")
        self.assertEqual(
            client.post.call_args.kwargs["json"]["variables"]["input"],
            {
                "teamId": "team-1",
                "title": "Fix it",
                "projectId": "project-1",
                "priority": 2,
            },
        )

    def test_update_issue_requires_at_least_one_field(self) -> None:
        service = LinearService({"api_key": "lin_api_test"}, client=MagicMock())

        with self.assertRaisesRegex(ValueError, "at least one field"):
            service.update_issue("ENG-1")

    def test_graphql_errors_raise_readable_value_error(self) -> None:
        client = MagicMock()
        client.post.return_value = _response({"errors": [{"message": "Not authorized"}]})
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with self.assertRaisesRegex(ValueError, "Not authorized"):
            service.get_viewer()


def _make_linear_workflow(linear_data: dict) -> tuple[list[dict], list[dict], dict]:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "linear",
            "type": "linear",
            "position": {"x": 200, "y": 0},
            "data": {"label": "linearNode", **linear_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$linearNode", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "linear"},
        {"id": "e2", "source": "linear", "target": "out"},
    ]
    return nodes, edges, {"text": "hello"}


class LinearExecutorBranchTests(unittest.TestCase):
    def test_create_issue_resolves_expressions_and_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "createIssue",
                "linearTeamId": "team-1",
                "linearProjectId": "project-1",
                "linearTitle": "Issue: $input.text",
                "linearDescription": "$input.text",
                "linearAssigneeId": "",
                "linearPriority": "2",
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}",
                type=CredentialType.linear,
            )
            mock_session.return_value = mock_db
            with patch(
                "app.services.encryption.decrypt_config",
                return_value={"api_key": "lin_api_test"},
            ):
                with patch(
                    "app.services.linear_service.LinearService.create_issue",
                    return_value={
                        "id": "issue-1",
                        "identifier": "ENG-1",
                        "url": "https://linear.app/issue/ENG-1",
                    },
                ) as mock_create:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=uuid.uuid4(),
                    )
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs=inputs,
                    )

        mock_create.assert_called_once_with(
            "team-1",
            "Issue: hello",
            description="hello",
            project_id="project-1",
            assignee_id=None,
            priority=2,
        )
        self.assertEqual(result.status, "success")

    def test_rejects_non_linear_credential(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "listTeams",
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
            executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
            result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=inputs)

        self.assertEqual(result.status, "error")
        linear_result = next(
            item for item in result.node_results if item["node_label"] == "linearNode"
        )
        self.assertIn("Linear credential", linear_result["error"])
