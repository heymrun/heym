"""Sentry REST API client used by workflow nodes and credentials."""

from typing import Any
from urllib.parse import urlparse

import httpx

from app.http_identity import merge_outbound_headers


class SentryService:
    """Small synchronous client for common Sentry API operations."""

    DEFAULT_BASE_URL = "https://sentry.io"
    _REQUEST_TIMEOUT_SECONDS = 30.0
    _MAX_LIMIT = 100

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
        return value.rstrip("/")

    @staticmethod
    def _normalize_limit(value: int | str | None, default: int = 25) -> int:
        try:
            limit = int(float(value if value is not None else default))
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, SentryService._MAX_LIMIT))

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if detail:
                return str(detail)
            if payload.get("error"):
                return str(payload["error"])
        return response.text

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

    def test_connection(self) -> dict[str, Any]:
        """Validate the token by listing visible organizations."""
        result = self._request("GET", "/organizations/", operation="connection test")
        if not isinstance(result, list):
            raise ValueError("Sentry connection test returned an unexpected response")
        return {"organizations": result, "count": len(result)}

    def list_organizations(self, limit: int | str | None = 25) -> list[dict[str, Any]]:
        """List organizations visible to the token."""
        result = self._request(
            "GET",
            "/organizations/",
            operation="listOrganizations",
            params={"per_page": self._normalize_limit(limit)},
        )
        return result if isinstance(result, list) else []

    def list_projects(
        self, organization_slug: str, limit: int | str | None = 25
    ) -> list[dict[str, Any]]:
        """List projects for an organization."""
        result = self._request(
            "GET",
            f"/organizations/{organization_slug}/projects/",
            operation="listProjects",
            params={"per_page": self._normalize_limit(limit)},
        )
        return result if isinstance(result, list) else []

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
            f"/teams/{organization_slug}/{team_slug}/projects/",
            operation="createProject",
            json=payload,
            success_codes=(200, 201),
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry createProject returned an unexpected response")
        return result

    def list_teams(
        self, organization_slug: str, limit: int | str | None = 25
    ) -> list[dict[str, Any]]:
        """List teams for an organization."""
        result = self._request(
            "GET",
            f"/organizations/{organization_slug}/teams/",
            operation="listTeams",
            params={"per_page": self._normalize_limit(limit)},
        )
        return result if isinstance(result, list) else []

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
            f"/organizations/{organization_slug}/teams/",
            operation="createTeam",
            json=payload,
            success_codes=(200, 201),
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry createTeam returned an unexpected response")
        return result

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
        params: dict[str, Any] = {"per_page": self._normalize_limit(limit)}
        if project_slug:
            params["project"] = project_slug
        if query:
            params["query"] = query
        if stats_period:
            params["statsPeriod"] = stats_period
        result = self._request(
            "GET",
            f"/organizations/{organization_slug}/issues/",
            operation="listIssues",
            params=params,
        )
        return result if isinstance(result, list) else []

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        """Fetch a Sentry issue by ID."""
        result = self._request("GET", f"/issues/{issue_id}/", operation="getIssue")
        if not isinstance(result, dict):
            raise ValueError("Sentry getIssue returned an unexpected response")
        return result

    def update_issue(
        self, issue_id: str, *, status: str | None = None, assigned_to: str | None = None
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
            f"/issues/{issue_id}/",
            operation="updateIssue",
            json=payload,
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry updateIssue returned an unexpected response")
        return result

    def list_events(
        self,
        organization_slug: str,
        *,
        project_slug: str,
        query: str | None = None,
        limit: int | str | None = 25,
    ) -> list[dict[str, Any]]:
        """List events for a project."""
        params: dict[str, Any] = {"per_page": self._normalize_limit(limit)}
        if query:
            params["query"] = query
        result = self._request(
            "GET",
            f"/projects/{organization_slug}/{project_slug}/events/",
            operation="listEvents",
            params=params,
        )
        return result if isinstance(result, list) else []

    def get_event(self, organization_slug: str, project_slug: str, event_id: str) -> dict[str, Any]:
        """Fetch a project event."""
        result = self._request(
            "GET",
            f"/projects/{organization_slug}/{project_slug}/events/{event_id}/",
            operation="getEvent",
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry getEvent returned an unexpected response")
        return result

    def list_releases(
        self, organization_slug: str, limit: int | str | None = 25
    ) -> list[dict[str, Any]]:
        """List releases for an organization."""
        result = self._request(
            "GET",
            f"/organizations/{organization_slug}/releases/",
            operation="listReleases",
            params={"per_page": self._normalize_limit(limit)},
        )
        return result if isinstance(result, list) else []

    def get_release(self, organization_slug: str, version: str) -> dict[str, Any]:
        """Fetch a release by version."""
        result = self._request(
            "GET",
            f"/organizations/{organization_slug}/releases/{version}/",
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
            f"/organizations/{organization_slug}/releases/",
            operation="createRelease",
            json=payload,
            success_codes=(200, 201),
        )
        if not isinstance(result, dict):
            raise ValueError("Sentry createRelease returned an unexpected response")
        return result
