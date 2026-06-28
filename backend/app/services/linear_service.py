import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.http_identity import merge_outbound_headers
from app.services.encryption import encrypt_config

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
LINEAR_OAUTH_TOKEN_URL = "https://api.linear.app/oauth/token"
_MAX_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_RETRY_DELAY_SECONDS = 1.0
_MAX_PAGINATED_RESULTS = 10_000
_UNSET = object()


class LinearService:
    """Small GraphQL client for common Linear workspace and issue operations."""

    def __init__(
        self,
        config: dict[str, Any],
        client: httpx.Client | None = None,
        credential_id: str | None = None,
    ) -> None:
        self._config = dict(config)
        self._credential_id = credential_id
        self._auth_mode = str(self._config.get("auth_mode", "api_key") or "api_key").strip()
        self._client = client or httpx.Client(
            headers=merge_outbound_headers(
                {
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

    @property
    def _authorization_header(self) -> str:
        token = self._get_valid_token()
        return f"Bearer {token}" if self._auth_mode == "oauth" else token

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

    def list_teams(
        self,
        limit: int = 50,
        after: str | None = None,
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """List teams visible to the authenticated user."""
        query = """
        query Teams($first: Int!, $after: String) {
          teams(first: $first, after: $after) {
            nodes { id key name description }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        if fetch_all:
            return self._list_all_pages(
                lambda page_limit, page_after: self._list_connection(
                    query,
                    {"first": page_limit, "after": page_after},
                    "teams",
                ),
                after=after,
            )
        return self._list_connection(
            query,
            {"first": self._normalize_limit(limit), "after": after},
            "teams",
        )

    def list_projects(
        self,
        limit: int = 50,
        after: str | None = None,
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """List projects visible to the authenticated user."""
        query = """
        query Projects($first: Int!, $after: String) {
          projects(first: $first, after: $after) {
            nodes {
              id name description state progress targetDate
              teams { nodes { id key name } }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        if fetch_all:
            return self._list_all_pages(
                lambda page_limit, page_after: self._list_connection(
                    query,
                    {"first": page_limit, "after": page_after},
                    "projects",
                ),
                after=after,
            )
        return self._list_connection(
            query,
            {"first": self._normalize_limit(limit), "after": after},
            "projects",
        )

    def list_issues(
        self,
        limit: int = 50,
        team_id: str | None = None,
        project_id: str | None = None,
        after: str | None = None,
        fetch_all: bool = False,
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
        if fetch_all:
            return self._list_all_pages(
                lambda page_limit, page_after: self._list_connection(
                    query,
                    {**variables, "first": page_limit, "after": page_after},
                    "issues",
                ),
                after=after,
            )
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
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """List members of a team."""
        query = """
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
        """

        def _fetch_page(page_limit: int, page_after: str | None) -> dict[str, Any]:
            data = self._execute(
                query,
                {
                    "teamId": team_id,
                    "first": page_limit,
                    "after": page_after,
                },
            )
            team = data.get("team")
            if team is None:
                raise ValueError(f"Linear team not found: {team_id}")
            team_payload = self._expect_object(team, "team")
            return self._connection_page(team_payload.get("members"), "team.members")

        if fetch_all:
            return self._list_all_pages(_fetch_page, after=after)

        return _fetch_page(self._normalize_limit(limit), after)

    def _get_valid_token(self) -> str:
        if self._auth_mode == "oauth":
            token = str(self._config.get("access_token", "") or "").strip()
            if not token:
                raise ValueError("Linear OAuth credential requires access_token")
            if self._is_oauth_token_expired():
                self._refresh_oauth_token()
                token = str(self._config.get("access_token", "") or "").strip()
            return token
        return self._normalize_api_key(str(self._config.get("api_key", "") or ""))

    def _is_oauth_token_expired(self) -> bool:
        expiry_str = str(self._config.get("token_expiry", "") or "").strip()
        if not expiry_str:
            return False
        try:
            expiry = datetime.fromisoformat(expiry_str)
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expiry - timedelta(seconds=60)

    def _refresh_oauth_token(self) -> None:
        refresh_token = str(self._config.get("refresh_token", "") or "").strip()
        client_id = str(self._config.get("client_id", "") or "").strip()
        client_secret = str(self._config.get("client_secret", "") or "").strip()
        if not refresh_token or not client_id or not client_secret:
            raise ValueError(
                "Linear OAuth credential requires refresh_token and client credentials"
            )
        try:
            response = self._client.post(
                LINEAR_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            response.raise_for_status()
            token_data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ValueError(f"Linear OAuth token refresh failed: {exc}") from exc
        if not isinstance(token_data, dict) or not token_data.get("access_token"):
            raise ValueError("Linear OAuth token refresh returned an invalid response")
        self._config["access_token"] = token_data["access_token"]
        if token_data.get("refresh_token"):
            self._config["refresh_token"] = token_data["refresh_token"]
        if token_data.get("expires_in"):
            self._config["token_expiry"] = (
                datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]))
            ).isoformat()
        self._persist_config()

    def _persist_config(self) -> None:
        if not self._credential_id:
            return
        from app.db.models import Credential
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            cred = db.query(Credential).filter(Credential.id == self._credential_id).first()
            if cred:
                cred.encrypted_config = encrypt_config(self._config)
                db.commit()

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
        state_id: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a Linear issue."""
        issue_input: dict[str, Any] = {"teamId": team_id, "title": title}
        for key, value in {
            "description": description,
            "projectId": project_id,
            "assigneeId": assignee_id,
            "stateId": state_id,
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
        team_id: Any = _UNSET,
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
            "teamId": team_id,
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

    def delete_issue(self, issue_id: str) -> dict[str, Any]:
        """Delete a Linear issue."""
        data = self._execute(
            """
            mutation DeleteIssue($id: String!) {
              issueDelete(id: $id) { success }
            }
            """,
            {"id": issue_id},
        )
        return self._expect_mutation_payload(data.get("issueDelete"), "issueDelete")

    def add_issue_link(self, issue_id: str, url: str) -> dict[str, Any]:
        """Add an external link attachment to a Linear issue."""
        data = self._execute(
            """
            mutation AddIssueLink($issueId: String!, $url: String!) {
              attachmentLinkURL(issueId: $issueId, url: $url) { success }
            }
            """,
            {"issueId": issue_id, "url": url},
        )
        return self._expect_mutation_payload(
            data.get("attachmentLinkURL"),
            "attachmentLinkURL",
        )

    def create_comment(
        self,
        issue_id: str,
        body: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a comment to a Linear issue."""
        comment_input: dict[str, Any] = {"issueId": issue_id, "body": body}
        if parent_id:
            comment_input["parentId"] = parent_id
        data = self._execute(
            """
            mutation CreateComment($input: CommentCreateInput!) {
              commentCreate(input: $input) {
                success
                comment { id body createdAt user { id name email } }
              }
            }
            """,
            {"input": comment_input},
        )
        payload = self._expect_mutation_payload(data.get("commentCreate"), "commentCreate")
        return self._expect_object(payload.get("comment"), "commentCreate.comment")

    def list_comments(
        self,
        issue_id: str,
        limit: int = 50,
        after: str | None = None,
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        """List comments on a Linear issue."""
        query = """
        query IssueComments($id: String!, $first: Int!, $after: String) {
          issue(id: $id) {
            comments(first: $first, after: $after) {
              nodes {
                id body url createdAt updatedAt editedAt resolvedAt
                issueId parentId resolvingCommentId
                user { id name email }
              }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """

        def _fetch_page(page_limit: int, page_after: str | None) -> dict[str, Any]:
            data = self._execute(
                query,
                {
                    "id": issue_id,
                    "first": page_limit,
                    "after": page_after,
                },
            )
            issue = data.get("issue")
            if issue is None:
                raise ValueError(f"Linear issue not found: {issue_id}")
            issue_payload = self._expect_object(issue, "issue")
            return self._connection_page(issue_payload.get("comments"), "issue.comments")

        if fetch_all:
            return self._list_all_pages(_fetch_page, after=after)

        return _fetch_page(self._normalize_limit(limit), after)

    def update_comment(self, comment_id: str, body: str) -> dict[str, Any]:
        """Update a Linear comment body."""
        data = self._execute(
            """
            mutation UpdateComment($id: String!, $input: CommentUpdateInput!) {
              commentUpdate(id: $id, input: $input) {
                success
                comment {
                  id body url createdAt updatedAt editedAt resolvedAt
                  issueId parentId resolvingCommentId
                  user { id name email }
                }
              }
            }
            """,
            {"id": comment_id, "input": {"body": body}},
        )
        payload = self._expect_mutation_payload(data.get("commentUpdate"), "commentUpdate")
        return self._expect_object(payload.get("comment"), "commentUpdate.comment")

    def delete_comment(self, comment_id: str) -> dict[str, Any]:
        """Delete a Linear comment."""
        data = self._execute(
            """
            mutation DeleteComment($id: String!) {
              commentDelete(id: $id) { success entityId }
            }
            """,
            {"id": comment_id},
        )
        return self._expect_mutation_payload(data.get("commentDelete"), "commentDelete")

    def resolve_comment(self, comment_id: str) -> dict[str, Any]:
        """Resolve a Linear comment thread."""
        data = self._execute(
            """
            mutation ResolveComment($id: String!) {
              commentResolve(id: $id) {
                success
                comment { id body url resolvedAt resolvingCommentId }
              }
            }
            """,
            {"id": comment_id},
        )
        payload = self._expect_mutation_payload(data.get("commentResolve"), "commentResolve")
        return self._expect_object(payload.get("comment"), "commentResolve.comment")

    def unresolve_comment(self, comment_id: str) -> dict[str, Any]:
        """Unresolve a Linear comment thread."""
        data = self._execute(
            """
            mutation UnresolveComment($id: String!) {
              commentUnresolve(id: $id) {
                success
                comment { id body url resolvedAt resolvingCommentId }
              }
            }
            """,
            {"id": comment_id},
        )
        payload = self._expect_mutation_payload(
            data.get("commentUnresolve"),
            "commentUnresolve",
        )
        return self._expect_object(payload.get("comment"), "commentUnresolve.comment")

    def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._get_valid_token():
            if self._auth_mode == "oauth":
                raise ValueError("Linear OAuth credential requires access_token")
            raise ValueError("Linear credential requires api_key")

        last_response: httpx.Response | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                last_response = self._client.post(
                    LINEAR_GRAPHQL_URL,
                    headers={"Authorization": self._authorization_header},
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

    def _list_all_pages(
        self,
        fetch_page: Any,
        *,
        after: str | None = None,
    ) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        cursor = after
        page_info = {"hasNextPage": False, "endCursor": None}
        while True:
            page = fetch_page(250, cursor)
            nodes.extend(page["nodes"])
            page_info = page["pageInfo"]
            if len(nodes) > _MAX_PAGINATED_RESULTS:
                raise ValueError("Linear pagination exceeded 10000 results")
            if not page_info.get("hasNextPage"):
                return {"nodes": nodes, "pageInfo": page_info}
            cursor = page_info.get("endCursor")
            if not cursor:
                return {"nodes": nodes, "pageInfo": page_info}

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
