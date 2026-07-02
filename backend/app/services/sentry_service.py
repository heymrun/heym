"""Sentry REST API client used by workflow nodes and credentials."""

from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.http_identity import merge_outbound_headers


class SentryService:
    """Small synchronous client for common Sentry API operations."""

    DEFAULT_BASE_URL = "https://sentry.io"
    _REQUEST_TIMEOUT_SECONDS = 30.0
    _MAX_PAGE_LIMIT = 100
    _MAX_TOTAL_LIMIT = 1000
    _MAX_ERROR_MESSAGE_LENGTH = 1000

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        token = str(config.get("api_token", "") or "").strip()
        if not token:
            raise ValueError("Sentry credential requires api_token")
        base_url = str(config.get("base_url", "") or self.DEFAULT_BASE_URL).strip()
        self._base_url = self._normalize_base_url(base_url)
        self._headers = merge_outbound_headers(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self._client = client or httpx.Client(
            headers=self._headers,
            timeout=httpx.Timeout(self._REQUEST_TIMEOUT_SECONDS),
            follow_redirects=True,
        )
        self._owns_client = client is None

    def close(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Sentry base_url must be a valid http(s) URL")
        normalized = parsed._replace(query="", fragment="").geturl()
        return normalized.rstrip("/")

    @staticmethod
    def _path_segment(value: str) -> str:
        return quote(value, safe="")

    @staticmethod
    def _normalize_limit(value: int | str | None, default: int = 25, maximum: int = 100) -> int:
        try:
            limit = int(float(value if value is not None else default))
        except (OverflowError, TypeError, ValueError):
            limit = default
        return max(1, min(limit, maximum))

    @classmethod
    def _truncate_error_message(cls, value: str) -> str:
        message = value.strip()
        if len(message) <= cls._MAX_ERROR_MESSAGE_LENGTH:
            return message
        return f"{message[: cls._MAX_ERROR_MESSAGE_LENGTH].rstrip()}..."

    @classmethod
    def _error_message(cls, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return cls._truncate_error_message(response.text)
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if detail:
                return cls._truncate_error_message(str(detail))
            if payload.get("error"):
                return cls._truncate_error_message(str(payload["error"]))
        return cls._truncate_error_message(response.text)

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        success_codes: tuple[int, ...] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}/api/0{path}",
                headers=self._headers,
                params=params,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Sentry {operation} failed: {exc}") from exc
        if success_codes is None:
            success = response.is_success
        else:
            success = response.status_code in success_codes
        if not success:
            raise ValueError(
                f"Sentry {operation} failed ({response.status_code}): "
                f"{self._error_message(response)}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Sentry {operation} returned invalid JSON") from exc

    @staticmethod
    def _next_cursor(response: httpx.Response) -> str | None:
        next_link = response.links.get("next")
        if not next_link or next_link.get("results") != "true":
            return None
        cursor = next_link.get("cursor")
        return str(cursor) if cursor else None

    def _request_list(
        self,
        path: str,
        *,
        operation: str,
        limit: int | str | None = 25,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        total_limit = self._normalize_limit(limit, maximum=self._MAX_TOTAL_LIMIT)
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        base_params = dict(params or {})

        while len(items) < total_limit:
            page_params = {
                **base_params,
                "per_page": self._normalize_limit(
                    total_limit - len(items),
                    maximum=self._MAX_PAGE_LIMIT,
                ),
            }
            if cursor:
                page_params["cursor"] = cursor

            try:
                response = self._client.request(
                    "GET",
                    f"{self._base_url}/api/0{path}",
                    headers=self._headers,
                    params=page_params,
                )
            except httpx.HTTPError as exc:
                raise ValueError(f"Sentry {operation} failed: {exc}") from exc

            if not response.is_success:
                raise ValueError(
                    f"Sentry {operation} failed ({response.status_code}): "
                    f"{self._error_message(response)}"
                )
            try:
                result = response.json()
            except ValueError as exc:
                raise ValueError(f"Sentry {operation} returned invalid JSON") from exc
            if not isinstance(result, list):
                raise ValueError(f"Sentry {operation} returned an unexpected response")
            if any(not isinstance(item, dict) for item in result):
                raise ValueError(f"Sentry {operation} returned an unexpected response")

            items.extend(result)
            cursor = self._next_cursor(response)
            if not cursor or not result:
                break

        return items[:total_limit]

    def test_connection(self) -> dict[str, Any]:
        """Validate the token by listing visible organizations."""
        organizations = self._request_list(
            "/organizations/",
            operation="connection test",
            limit=1,
        )
        return {"organizations": organizations, "count": len(organizations)}

    def list_organizations(self, limit: int | str | None = 25) -> list[dict[str, Any]]:
        """List organizations visible to the token."""
        return self._request_list(
            "/organizations/",
            operation="listOrganizations",
            limit=limit,
        )

    def update_organization(
        self, organization_slug: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an organization."""
        result = self._request(
            "PUT",
            f"/organizations/{self._path_segment(organization_slug)}/",
            operation="updateOrganization",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry updateOrganization returned an unexpected response")
        return result

    def list_projects(
        self, organization_slug: str, limit: int | str | None = 25
    ) -> list[dict[str, Any]]:
        """List projects for an organization."""
        result = self._request_list(
            f"/organizations/{self._path_segment(organization_slug)}/projects/",
            operation="listProjects",
            limit=limit,
        )
        return result

    def create_project(
        self,
        organization_slug: str,
        team_slug: str,
        name: str,
        *,
        slug: str | None = None,
        platform: str | None = None,
    ) -> dict[str, Any]:
        """Create a project inside a team."""
        payload: dict[str, Any] = {"name": name}
        if slug:
            payload["slug"] = slug
        if platform:
            payload["platform"] = platform
        result = self._request(
            "POST",
            f"/teams/{self._path_segment(organization_slug)}/{self._path_segment(team_slug)}/projects/",
            operation="createProject",
            json=payload,
            success_codes=(200, 201),
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry createProject returned an unexpected response")
        return result

    def get_project(self, organization_slug: str, project_slug: str) -> dict[str, Any]:
        """Fetch a project."""
        result = self._request(
            "GET",
            (
                f"/projects/{self._path_segment(organization_slug)}/"
                f"{self._path_segment(project_slug)}/"
            ),
            operation="getProject",
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry getProject returned an unexpected response")
        return result

    def update_project(
        self, organization_slug: str, project_slug: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a project."""
        result = self._request(
            "PUT",
            (
                f"/projects/{self._path_segment(organization_slug)}/"
                f"{self._path_segment(project_slug)}/"
            ),
            operation="updateProject",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry updateProject returned an unexpected response")
        return result

    def delete_project(self, organization_slug: str, project_slug: str) -> dict[str, Any]:
        """Delete a project."""
        self._request(
            "DELETE",
            (
                f"/projects/{self._path_segment(organization_slug)}/"
                f"{self._path_segment(project_slug)}/"
            ),
            operation="deleteProject",
            success_codes=(200, 202, 204),
        )
        return {
            "deleted": True,
            "organization_slug": organization_slug,
            "project_slug": project_slug,
        }

    def list_teams(
        self, organization_slug: str, limit: int | str | None = 25
    ) -> list[dict[str, Any]]:
        """List teams for an organization."""
        result = self._request_list(
            f"/organizations/{self._path_segment(organization_slug)}/teams/",
            operation="listTeams",
            limit=limit,
        )
        return result

    def create_team(
        self,
        organization_slug: str,
        name: str,
        *,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Create a team in an organization."""
        payload: dict[str, Any] = {"name": name}
        if slug:
            payload["slug"] = slug
        result = self._request(
            "POST",
            f"/organizations/{self._path_segment(organization_slug)}/teams/",
            operation="createTeam",
            json=payload,
            success_codes=(200, 201),
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry createTeam returned an unexpected response")
        return result

    def update_team(
        self, organization_slug: str, team_slug: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a team."""
        result = self._request(
            "PUT",
            (f"/teams/{self._path_segment(organization_slug)}/{self._path_segment(team_slug)}/"),
            operation="updateTeam",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry updateTeam returned an unexpected response")
        return result

    def delete_team(self, organization_slug: str, team_slug: str) -> dict[str, Any]:
        """Delete a team."""
        self._request(
            "DELETE",
            (f"/teams/{self._path_segment(organization_slug)}/{self._path_segment(team_slug)}/"),
            operation="deleteTeam",
            success_codes=(200, 202, 204),
        )
        return {"deleted": True, "organization_slug": organization_slug, "team_slug": team_slug}

    def list_issues(
        self,
        organization_slug: str,
        *,
        project_slug: str | None = None,
        query: str | None = None,
        stats_period: str | None = None,
        limit: int | str | None = 25,
    ) -> list[dict[str, Any]]:
        """List issues for an organization, optionally filtered to a project."""
        params: dict[str, Any] = {}
        if project_slug:
            params["project"] = project_slug
        if query is not None:
            params["query"] = query
        if stats_period:
            params["statsPeriod"] = stats_period
        result = self._request_list(
            f"/organizations/{self._path_segment(organization_slug)}/issues/",
            operation="listIssues",
            limit=limit,
            params=params,
        )
        return result

    def get_issue(self, organization_slug: str, issue_id: str) -> dict[str, Any]:
        """Fetch a Sentry issue by ID."""
        result = self._request(
            "GET",
            (
                f"/organizations/{self._path_segment(organization_slug)}/"
                f"issues/{self._path_segment(issue_id)}/"
            ),
            operation="getIssue",
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry getIssue returned an unexpected response")
        return result

    def update_issue(
        self,
        organization_slug: str,
        issue_id: str,
        *,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any]:
        """Update a Sentry issue status or assignment."""
        payload: dict[str, Any] = {}
        if status:
            payload["status"] = status
        if assigned_to:
            payload["assignedTo"] = assigned_to
        if not payload:
            raise ValueError("Sentry updateIssue requires status or assignedTo")
        result = self._request(
            "PUT",
            (
                f"/organizations/{self._path_segment(organization_slug)}/"
                f"issues/{self._path_segment(issue_id)}/"
            ),
            operation="updateIssue",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry updateIssue returned an unexpected response")
        return result

    def delete_issue(self, organization_slug: str, issue_id: str) -> dict[str, Any]:
        """Delete a Sentry issue by ID."""
        self._request(
            "DELETE",
            (
                f"/organizations/{self._path_segment(organization_slug)}/"
                f"issues/{self._path_segment(issue_id)}/"
            ),
            operation="deleteIssue",
            success_codes=(200, 202, 204),
        )
        return {"deleted": True, "organization_slug": organization_slug, "issue_id": issue_id}

    def list_events(
        self,
        organization_slug: str,
        *,
        project_slug: str,
        query: str | None = None,
        limit: int | str | None = 25,
    ) -> list[dict[str, Any]]:
        """List events for a project."""
        params: dict[str, Any] = {}
        if query:
            params["query"] = query
        result = self._request_list(
            f"/projects/{self._path_segment(organization_slug)}/{self._path_segment(project_slug)}/events/",
            operation="listEvents",
            limit=limit,
            params=params,
        )
        return result

    def get_event(self, organization_slug: str, project_slug: str, event_id: str) -> dict[str, Any]:
        """Fetch a project event."""
        result = self._request(
            "GET",
            (
                f"/projects/{self._path_segment(organization_slug)}/"
                f"{self._path_segment(project_slug)}/events/{self._path_segment(event_id)}/"
            ),
            operation="getEvent",
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry getEvent returned an unexpected response")
        return result

    def list_releases(
        self, organization_slug: str, limit: int | str | None = 25
    ) -> list[dict[str, Any]]:
        """List releases for an organization."""
        result = self._request_list(
            f"/organizations/{self._path_segment(organization_slug)}/releases/",
            operation="listReleases",
            limit=limit,
        )
        return result

    def get_release(self, organization_slug: str, version: str) -> dict[str, Any]:
        """Fetch a release by version."""
        result = self._request(
            "GET",
            (
                f"/organizations/{self._path_segment(organization_slug)}/"
                f"releases/{self._path_segment(version)}/"
            ),
            operation="getRelease",
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry getRelease returned an unexpected response")
        return result

    def create_release(
        self,
        organization_slug: str,
        version: str,
        *,
        projects: list[str] | None = None,
        refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a release for an organization."""
        payload: dict[str, Any] = {"version": version}
        if projects:
            payload["projects"] = projects
        if refs:
            payload["refs"] = refs
        result = self._request(
            "POST",
            f"/organizations/{self._path_segment(organization_slug)}/releases/",
            operation="createRelease",
            json=payload,
            success_codes=(200, 201),
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry createRelease returned an unexpected response")
        return result

    def update_release(
        self, organization_slug: str, version: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a release."""
        result = self._request(
            "PUT",
            (
                f"/organizations/{self._path_segment(organization_slug)}/"
                f"releases/{self._path_segment(version)}/"
            ),
            operation="updateRelease",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry updateRelease returned an unexpected response")
        return result

    def delete_release(self, organization_slug: str, version: str) -> dict[str, Any]:
        """Delete a release."""
        self._request(
            "DELETE",
            (
                f"/organizations/{self._path_segment(organization_slug)}/"
                f"releases/{self._path_segment(version)}/"
            ),
            operation="deleteRelease",
            success_codes=(200, 202, 204),
        )
        return {"deleted": True, "organization_slug": organization_slug, "version": version}
