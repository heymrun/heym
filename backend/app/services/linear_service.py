from typing import Any

import httpx

from app.http_identity import merge_outbound_headers

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"


class LinearService:
    """Small GraphQL client for common Linear workspace and issue operations."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self._api_key = str(config.get("api_key", "") or "").strip()
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

    def list_teams(self, limit: int = 50) -> list[dict[str, Any]]:
        """List teams visible to the authenticated user."""
        data = self._execute(
            """
            query Teams($first: Int!) {
              teams(first: $first) {
                nodes { id key name description }
              }
            }
            """,
            {"first": self._normalize_limit(limit)},
        )
        return self._connection_nodes(data, "teams")

    def list_projects(self, limit: int = 50) -> list[dict[str, Any]]:
        """List projects visible to the authenticated user."""
        data = self._execute(
            """
            query Projects($first: Int!) {
              projects(first: $first) {
                nodes {
                  id name description state progress targetDate
                  teams { nodes { id key name } }
                }
              }
            }
            """,
            {"first": self._normalize_limit(limit)},
        )
        return self._connection_nodes(data, "projects")

    def list_issues(
        self,
        limit: int = 50,
        team_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List issues with optional team and project filters."""
        filters: list[str] = []
        variables: dict[str, Any] = {"first": self._normalize_limit(limit)}
        variable_definitions = ["$first: Int!"]
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
              issues(first: $first{filter_argument}) {{
                nodes {{
                  id identifier title description priority url createdAt updatedAt
                  team {{ id key name }}
                  project {{ id name }}
                  state {{ id name type color }}
                  assignee {{ id name email }}
                }}
              }}
            }}
        """
        data = self._execute(query, variables)
        return self._connection_nodes(data, "issues")

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
        return self._expect_object(data.get("issue"), "issue")

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
        payload = self._expect_object(data.get("issueCreate"), "issueCreate")
        if not payload.get("success"):
            raise ValueError("Linear issueCreate did not succeed")
        return self._expect_object(payload.get("issue"), "issueCreate.issue")

    def update_issue(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        state_id: str | None = None,
        project_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
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
            if value is not None and value != "":
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
        payload = self._expect_object(data.get("issueUpdate"), "issueUpdate")
        if not payload.get("success"):
            raise ValueError("Linear issueUpdate did not succeed")
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
        payload = self._expect_object(data.get("commentCreate"), "commentCreate")
        if not payload.get("success"):
            raise ValueError("Linear commentCreate did not succeed")
        return self._expect_object(payload.get("comment"), "commentCreate.comment")

    def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.post(
            LINEAR_GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": self._api_key},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            raise ValueError(
                f"Linear API request failed with status {response.status_code}: {detail}"
            ) from exc
        payload = response.json()
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

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        return max(1, min(limit, 250))

    @staticmethod
    def _expect_object(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"Linear API returned an invalid {label} payload")
        return value

    @classmethod
    def _connection_nodes(cls, data: dict[str, Any], field: str) -> list[dict[str, Any]]:
        connection = cls._expect_object(data.get(field), field)
        nodes = connection.get("nodes")
        if not isinstance(nodes, list):
            raise ValueError(f"Linear API returned an invalid {field}.nodes payload")
        return [node for node in nodes if isinstance(node, dict)]
