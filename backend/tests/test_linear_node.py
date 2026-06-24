"""Unit tests for LinearService and the workflow executor Linear branch."""

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.linear_service import _UNSET, LINEAR_GRAPHQL_URL, LinearService


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
        client.post.assert_called_once()

    def test_test_connection_returns_viewer(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {"data": {"viewer": {"id": "user-1", "displayName": "Ada Lovelace"}}}
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        viewer = service.test_connection()

        self.assertEqual(viewer["displayName"], "Ada Lovelace")

    def test_strips_bearer_prefix_from_api_key(self) -> None:
        client = MagicMock()
        client.post.return_value = _response({"data": {"viewer": {"id": "user-1", "name": "Ada"}}})
        service = LinearService({"api_key": "Bearer lin_api_test"}, client=client)

        service.get_viewer()

        self.assertEqual(service._api_key, "lin_api_test")

    def test_empty_api_key_raises_before_request(self) -> None:
        client = MagicMock()
        service = LinearService({"api_key": ""}, client=client)

        with self.assertRaisesRegex(ValueError, "requires api_key"):
            service.get_viewer()

        client.post.assert_not_called()

    def test_non_json_response_raises_readable_value_error(self) -> None:
        request = httpx.Request("POST", LINEAR_GRAPHQL_URL)
        response = httpx.Response(
            status_code=200,
            content=b"not json",
            request=request,
        )
        client = MagicMock()
        client.post.return_value = response
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with self.assertRaisesRegex(ValueError, "non-JSON"):
            service.get_viewer()

    def test_network_error_raises_readable_value_error(self) -> None:
        client = MagicMock()
        client.post.side_effect = httpx.ConnectError("connection refused")
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with self.assertRaisesRegex(ValueError, "Linear API request failed"):
            service.get_viewer()

    def test_rate_limit_retries_before_success(self) -> None:
        client = MagicMock()
        client.post.side_effect = [
            _response({"errors": [{"message": "Rate limit"}]}, status_code=429),
            _response({"data": {"viewer": {"id": "user-1", "name": "Ada"}}}),
        ]
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with patch("app.services.linear_service.time.sleep") as mock_sleep:
            result = service.get_viewer()

        self.assertEqual(result["name"], "Ada")
        self.assertEqual(client.post.call_count, 2)
        mock_sleep.assert_called_once()

    def test_get_issue_not_found_raises_clear_error(self) -> None:
        client = MagicMock()
        client.post.return_value = _response({"data": {"issue": None}})
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with self.assertRaisesRegex(ValueError, "Linear issue not found: ENG-404"):
            service.get_issue("ENG-404")

    def test_list_issues_builds_optional_filters_and_clamps_limit(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "data": {
                    "issues": {
                        "nodes": [{"id": "issue-1", "identifier": "ENG-1"}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    }
                }
            }
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        result = service.list_issues(999, team_id="team-1", project_id="project-1", after="cur-0")

        self.assertEqual(result["nodes"][0]["identifier"], "ENG-1")
        self.assertTrue(result["pageInfo"]["hasNextPage"])
        self.assertEqual(result["pageInfo"]["endCursor"], "cursor-1")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(
            payload["variables"],
            {
                "first": 250,
                "after": "cur-0",
                "teamId": "team-1",
                "projectId": "project-1",
            },
        )
        self.assertIn("team: { id: { eq: $teamId } }", payload["query"])
        self.assertIn("project: { id: { eq: $projectId } }", payload["query"])

    def test_list_workflow_states_returns_team_states(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "data": {
                    "team": {
                        "states": {
                            "nodes": [{"id": "state-1", "name": "Done", "type": "completed"}]
                        }
                    }
                }
            }
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        states = service.list_workflow_states("team-1")

        self.assertEqual(states[0]["name"], "Done")

    def test_list_team_members_returns_paginated_members(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "data": {
                    "team": {
                        "members": {
                            "nodes": [{"user": {"id": "user-1", "name": "Ada"}}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        result = service.list_team_members("team-1")

        self.assertEqual(result["nodes"][0]["user"]["name"], "Ada")

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

    def test_update_issue_can_clear_optional_fields_with_null(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"id": "issue-1", "identifier": "ENG-1"},
                    }
                }
            }
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        service.update_issue("ENG-1", assignee_id=None)

        issue_input = client.post.call_args.kwargs["json"]["variables"]["input"]
        self.assertIsNone(issue_input["assigneeId"])

    def test_update_issue_skips_unset_fields(self) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"id": "issue-1", "identifier": "ENG-1"},
                    }
                }
            }
        )
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        service.update_issue("ENG-1", title="Updated", description=_UNSET)

        issue_input = client.post.call_args.kwargs["json"]["variables"]["input"]
        self.assertEqual(issue_input, {"title": "Updated"})

    def test_graphql_errors_raise_readable_value_error(self) -> None:
        client = MagicMock()
        client.post.return_value = _response({"errors": [{"message": "Not authorized"}]})
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with self.assertRaisesRegex(ValueError, "Not authorized"):
            service.get_viewer()

    def test_http_error_raises_readable_value_error(self) -> None:
        client = MagicMock()
        client.post.return_value = _response({"message": "Unauthorized"}, status_code=401)
        service = LinearService({"api_key": "lin_api_test"}, client=client)

        with self.assertRaisesRegex(ValueError, "status 401"):
            service.get_viewer()

    def test_close_closes_owned_client(self) -> None:
        service = LinearService({"api_key": "lin_api_test"})
        mock_client = MagicMock()
        mock_client.is_closed = False
        service._client = mock_client

        service.close()

        mock_client.close.assert_called_once()


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

    def test_list_teams_returns_page_info(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "listTeams",
                "linearAfter": "cursor-1",
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
                    "app.services.linear_service.LinearService.list_teams",
                    return_value={
                        "nodes": [{"id": "team-1", "key": "ENG"}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-2"},
                    },
                ) as mock_list:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=uuid.uuid4(),
                    )
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs=inputs,
                    )

        mock_list.assert_called_once_with(50, after="cursor-1")
        self.assertEqual(result.status, "success")
        linear_result = next(
            item for item in result.node_results if item["node_label"] == "linearNode"
        )
        self.assertEqual(linear_result["output"]["count"], 1)
        self.assertTrue(linear_result["output"]["pageInfo"]["hasNextPage"])

    def test_list_workflow_states_calls_service(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "listWorkflowStates",
                "linearTeamId": "team-1",
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
                    "app.services.linear_service.LinearService.list_workflow_states",
                    return_value=[{"id": "state-1", "name": "Done"}],
                ) as mock_list:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=uuid.uuid4(),
                    )
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs=inputs,
                    )

        mock_list.assert_called_once_with("team-1")
        self.assertEqual(result.status, "success")
        linear_result = next(
            item for item in result.node_results if item["node_label"] == "linearNode"
        )
        self.assertEqual(linear_result["output"]["count"], 1)
        self.assertEqual(linear_result["output"]["states"][0]["name"], "Done")

    def test_list_team_members_returns_page_info(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "listTeamMembers",
                "linearTeamId": "team-1",
                "linearAfter": "cursor-1",
                "linearLimit": "25",
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
                    "app.services.linear_service.LinearService.list_team_members",
                    return_value={
                        "nodes": [{"user": {"id": "user-1", "name": "Ada"}}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    },
                ) as mock_list:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=uuid.uuid4(),
                    )
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs=inputs,
                    )

        mock_list.assert_called_once_with("team-1", 25, after="cursor-1")
        self.assertEqual(result.status, "success")
        linear_result = next(
            item for item in result.node_results if item["node_label"] == "linearNode"
        )
        self.assertEqual(linear_result["output"]["members"][0]["user"]["name"], "Ada")

    def test_update_issue_null_expression_clears_assignee(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "updateIssue",
                "linearIssueId": "ENG-1",
                "linearAssigneeId": "null",
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
                    "app.services.linear_service.LinearService.update_issue",
                    return_value={"id": "issue-1", "identifier": "ENG-1"},
                ) as mock_update:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=uuid.uuid4(),
                    )
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs=inputs,
                    )

        mock_update.assert_called_once_with("ENG-1", assignee_id=None)
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

    def test_update_issue_requires_at_least_one_field_in_executor(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_linear_workflow(
            {
                "credentialId": "cred-1",
                "linearOperation": "updateIssue",
                "linearIssueId": "ENG-1",
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
                with patch("app.services.linear_service.LinearService.update_issue") as mock_update:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=uuid.uuid4(),
                    )
                    result = executor.execute(
                        workflow_id=uuid.uuid4(),
                        initial_inputs=inputs,
                    )

        mock_update.assert_not_called()
        self.assertEqual(result.status, "error")
        linear_result = next(
            item for item in result.node_results if item["node_label"] == "linearNode"
        )
        self.assertIn("at least one field", linear_result["error"])
