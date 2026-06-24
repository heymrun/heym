import time
from typing import Any

import httpx

from app.http_identity import merge_outbound_headers

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
_MAX_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_RETRY_DELAY_SECONDS = 1.0
_UNSET = object()


class LinearService:
    """Small GraphQL client for common Linear workspace and issue operations."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self._api_key = self._normalize_api_key(str(config.get("api_key", "") or ""))
        self._client = client or httpx.Client(
            headers=merge_outbound_headers(
                {
                    "Authorization": self._api_key,
                    "Content-Type": "application/json",
                }
            ),
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        self._owns_client = client is None

    def close(self) -> None:
        """Close the internally owned HTTP client, if any."""
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    def test_connection(self) -> dict[str, Any]:
        """Verify the API key by fetching the authenticated Linear user."""
        return self.get_viewer()

    def get_viewer(self) -> dict[str, Any]:
        """Return the authenticated Linear user."""
        data = self._execute(
            """
            query Viewer {
              viewer { id name displayName email active }
            }
            """
        )
        return self._expect_object(data.get("viewer"), "viewer")

    def list_teams(self, limit: int = 50, after: str | None = None) -> dict[str, Any]:
        """List teams visible to the authenticated user."""
        return self._list_connection(
            """
            query Teams($first: Int!, $after: String) {
              teams(first: $first, after: $after) {
                nodes { id key name description }
                pageInfo { hasNextPage endCursor }
              }
            }
            """,
            {"first": self._normalize_limit(limit), "after": after},
            "teams",
        )

    def list_projects(self, limit: int = 50, after: str | None = None) -> dict[str, Any]:
        """List projects visible to the authenticated user."""
        return self._list_connection(
            """
            query Projects($first: Int!, $after: String) {
              projects(first: $first, after: $after) {
                nodes {
                  id name description state progress targetDate
                  teams { nodes { id key name } }
                }
                pageInfo { hasNextPage endCursor }
              }
            }
            """,
            {"first": self._normalize_limit(limit), "after": after},
            "projects",
        )

    def list_issues(
        self,
        limit: int = 50,
        team_id: str | None = None,
        project_id: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List issues with optional team and project filters."""
        filters: list[str] = []
        variables: dict[str, Any] = {
            "first": self._normalize_limit(limit),
            "after": after,
        }
        variable_definitions = ["$first: Int!", "$after: String"]
        if team_id:
            filters.append("team: { id: { eq: $teamId } }")
            variables["teamId"] = team_id
            variable_definitions.append("$teamId: ID!")
        if project_id:
            filters.append("project: { id: { eq: $projectId } }")
            variables["projectId"] = project_id
            variable_definitions.append("$projectId: ID!")
        filter_argument = f", filter: {{ {', '.join(filters)} }}" if filters else ""
        query = f"""
            query Issues({", ".join(variable_definitions)}) {{
              issues(first: $first, after: $after{filter_argument}) {{
                nodes {{
                  id identifier title description priority url createdAt updatedAt
                  team {{ id key name }}
                  project {{ id name }}
                  state {{ id name type color }}
                  assignee {{ id name email }}
                }}
                pageInfo {{ hasNextPage endCursor }}
              }}
            }}
        """
        return self._list_connection(query, variables, "issues")

    def list_workflow_states(self, team_id: str) -> list[dict[str, Any]]:
        """List workflow states for a team."""
        data = self._execute(
            """
            query WorkflowStates($teamId: String!) {
              team(id: $teamId) {
                states { nodes { id name type color position } }
              }
            }
            """,
            {"teamId": team_id},
        )
        team = data.get("team")
        if team is None:
            raise ValueError(f"Linear team not found: {team_id}")
        team_payload = self._expect_object(team, "team")
        states = team_payload.get("states")
        if not isinstance(states, dict):
            raise ValueError("Linear API returned an invalid team.states payload")
        nodes = states.get("nodes")
        if not isinstance(nodes, list):
            raise ValueError("Linear API returned an invalid team.states.nodes payload")
        return [node for node in nodes if isinstance(node, dict)]

    def list_team_members(
        self,
        team_id: str,
        limit: int = 50,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List members of a team."""
        data = self._execute(
            """
            query TeamMembers($teamId: String!, $first: Int!, $after: String) {
              team(id: $teamId) {
                members(first: $first, after: $after) {
                  nodes {
                    id
                    user { id name email displayName active }
                  }
                  pageInfo { hasNextPage endCursor }
                }
              }
            }
            """,
            {
                "teamId": team_id,
                "first": self._normalize_limit(limit),
                "after": after,
            },
        )
        team = data.get("team")
        if team is None:
            raise ValueError(f"Linear team not found: {team_id}")
        team_payload = self._expect_object(team, "team")
        return self._connection_page(team_payload.get("members"), "team.members")

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        """Fetch one Linear issue by UUID or identifier."""
        data = self._execute(
            """
            query Issue($id: String!) {
              issue(id: $id) {
                id identifier title description priority url createdAt updatedAt
                team { id key name }
                project { id name }
                state { id name type color }
                assignee { id name email }
              }
            }
            """,
            {"id": issue_id},
        )
        issue = data.get("issue")
        if issue is None:
            raise ValueError(f"Linear issue not found: {issue_id}")
        return self._expect_object(issue, "issue")

    def create_issue(
        self,
        team_id: str,
        title: str,
        description: str | None = None,
        project_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a Linear issue."""
        issue_input: dict[str, Any] = {"teamId": team_id, "title": title}
        for key, value in {
            "description": description,
            "projectId": project_id,
            "assigneeId": assignee_id,
            "priority": priority,
        }.items():
            if value is not None and value != "":
                issue_input[key] = value
        data = self._execute(
            """
            mutation CreateIssue($input: IssueCreateInput!) {
              issueCreate(input: $input) {
                success
                issue { id identifier title description priority url }
              }
            }
            """,
            {"input": issue_input},
        )
        payload = self._expect_mutation_payload(data.get("issueCreate"), "issueCreate")
        return self._expect_object(payload.get("issue"), "issueCreate.issue")

    def update_issue(
        self,
        issue_id: str,
        *,
        title: Any = _UNSET,
        description: Any = _UNSET,
        state_id: Any = _UNSET,
        project_id: Any = _UNSET,
        assignee_id: Any = _UNSET,
        priority: Any = _UNSET,
    ) -> dict[str, Any]:
        """Update fields on an existing Linear issue."""
        issue_input: dict[str, Any] = {}
        for key, value in {
            "title": title,
            "description": description,
            "stateId": state_id,
            "projectId": project_id,
            "assigneeId": assignee_id,
            "priority": priority,
        }.items():
            if value is _UNSET:
                continue
            if value is None:
                issue_input[key] = None
            elif value != "":
                issue_input[key] = value
        if not issue_input:
            raise ValueError("Linear updateIssue requires at least one field to update")
        data = self._execute(
            """
            mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {
                success
                issue { id identifier title description priority url }
              }
            }
            """,
            {"id": issue_id, "input": issue_input},
        )
        payload = self._expect_mutation_payload(data.get("issueUpdate"), "issueUpdate")
        return self._expect_object(payload.get("issue"), "issueUpdate.issue")

    def create_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        """Add a comment to a Linear issue."""
        data = self._execute(
            """
            mutation CreateComment($input: CommentCreateInput!) {
              commentCreate(input: $input) {
                success
                comment { id body createdAt user { id name email } }
              }
            }
            """,
            {"input": {"issueId": issue_id, "body": body}},
        )
        payload = self._expect_mutation_payload(data.get("commentCreate"), "commentCreate")
        return self._expect_object(payload.get("comment"), "commentCreate.comment")

    def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("Linear credential requires api_key")

        last_response: httpx.Response | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                last_response = self._client.post(
                    LINEAR_GRAPHQL_URL,
                    json={"query": query, "variables": variables or {}},
                )
            except httpx.RequestError as exc:
                raise ValueError(f"Linear API request failed: {exc}") from exc

            if last_response.status_code == 429 and attempt < _MAX_RATE_LIMIT_RETRIES:
                time.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
                continue
            break

        assert last_response is not None
        response = last_response
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            raise ValueError(
                f"Linear API request failed with status {response.status_code}: {detail}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("Linear API returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise ValueError("Linear API returned an unexpected response")
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            messages = [
                str(error.get("message", "Unknown GraphQL error"))
                for error in errors
                if isinstance(error, dict)
            ]
            raise ValueError(f"Linear API error: {'; '.join(messages) or 'Unknown GraphQL error'}")
        return self._expect_object(payload.get("data"), "data")

    def _list_connection(
        self,
        query: str,
        variables: dict[str, Any],
        field: str,
    ) -> dict[str, Any]:
        data = self._execute(query, variables)
        return self._connection_page(data.get(field), field)

    @classmethod
    def _connection_page(cls, connection: Any, field: str) -> dict[str, Any]:
        connection_payload = cls._expect_object(connection, field)
        nodes = connection_payload.get("nodes")
        if not isinstance(nodes, list):
            raise ValueError(f"Linear API returned an invalid {field}.nodes payload")
        page_info = connection_payload.get("pageInfo")
        normalized_page_info = (
            cls._normalize_page_info(page_info)
            if isinstance(page_info, dict)
            else {"hasNextPage": False, "endCursor": None}
        )
        return {
            "nodes": [node for node in nodes if isinstance(node, dict)],
            "pageInfo": normalized_page_info,
        }

    @staticmethod
    def _normalize_page_info(page_info: dict[str, Any]) -> dict[str, Any]:
        end_cursor = page_info.get("endCursor")
        return {
            "hasNextPage": bool(page_info.get("hasNextPage")),
            "endCursor": str(end_cursor) if end_cursor else None,
        }

    @staticmethod
    def _expect_mutation_payload(value: Any, mutation_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"Linear API returned an invalid {mutation_name} payload")
        if not value.get("success"):
            raise ValueError(f"Linear {mutation_name} did not succeed")
        return value

    @staticmethod
    def _normalize_api_key(raw_api_key: str) -> str:
        api_key = raw_api_key.strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        return api_key

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        return max(1, min(limit, 250))

    @staticmethod
    def _expect_object(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"Linear API returned an invalid {label} payload")
        return value
