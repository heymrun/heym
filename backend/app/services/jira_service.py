from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from app.http_identity import merge_outbound_headers

_DEFAULT_API_VERSION = "3"
_DEFAULT_DEPLOYMENT = "cloud"
_DEFAULT_SEARCH_FIELDS = ["key", "summary", "status", "assignee", "issuetype"]
_DEFAULT_SEARCH_JQL = "updated >= -30d ORDER BY updated DESC"
_MAX_ERROR_DETAIL_CHARS = 500
_UNSET = object()


class JiraService:
    """Small REST client for common Jira project, issue, comment, attachment, and user operations."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self._config = dict(config)
        self._base_url = self._normalize_base_url(str(self._config.get("base_url", "") or ""))
        self._deployment = self._normalize_deployment(self._config)
        self._api_version = self._normalize_api_version(self._config, self._deployment)
        self._client = client or httpx.Client(
            headers=merge_outbound_headers({"Accept": "application/json"}),
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        self._owns_client = client is None

    def close(self) -> None:
        """Close the internally owned HTTP client, if any."""
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    def test_connection(self) -> dict[str, Any]:
        """Verify the credential by fetching the current Jira user."""
        return self.get_myself()

    def get_myself(self) -> dict[str, Any]:
        """Return the authenticated Jira user."""
        return self._expect_object(self._request("GET", "/myself"), "myself")

    def list_projects(self, limit: int = 50, start_at: int = 0) -> dict[str, Any]:
        """List Jira projects visible to the authenticated user."""
        normalized_limit = self._normalize_limit(limit)
        offset = max(start_at, 0)
        if self._is_data_center:
            payload = self._request("GET", "/project")
            projects = self._expect_project_list(payload)
            page = projects[offset : offset + normalized_limit]
            total = len(projects)
            return {
                "values": page,
                "startAt": offset,
                "maxResults": normalized_limit,
                "total": total,
                "isLast": offset + normalized_limit >= total,
            }
        payload = self._request(
            "GET",
            "/project/search",
            params={"maxResults": normalized_limit, "startAt": offset},
        )
        return self._expect_object(payload, "project.search")

    def search_issues(
        self,
        jql: str,
        limit: int = 50,
        *,
        next_page_token: str | None = None,
        start_at: int = 0,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search issues with JQL."""
        body: dict[str, Any] = {
            "jql": jql or _DEFAULT_SEARCH_JQL,
            "maxResults": self._normalize_limit(limit),
            "fields": fields or list(_DEFAULT_SEARCH_FIELDS),
        }
        if self._is_data_center:
            body["startAt"] = max(start_at, 0)
            payload = self._request("POST", "/search", json=body)
            return self._expect_object(payload, "issue.search")
        if next_page_token:
            body["nextPageToken"] = next_page_token
        payload = self._request("POST", "/search/jql", json=body)
        return self._expect_object(payload, "issue.search")

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch one Jira issue by key or ID."""
        payload = self._request("GET", f"/issue/{issue_key}")
        return self._expect_object(payload, "issue")

    def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str | None = None,
        assignee_account_id: str | None = None,
        labels: list[str] | None = None,
        issue_type_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a Jira issue."""
        issuetype: dict[str, str]
        if issue_type_id:
            issuetype = {"id": issue_type_id}
        else:
            issuetype = {"name": issue_type}
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": issuetype,
            "summary": summary,
        }
        if description:
            fields["description"] = self._text_document_payload(description)
        if assignee_account_id:
            fields["assignee"] = self._user_identity_payload(assignee_account_id)
        if labels:
            fields["labels"] = labels
        return self._expect_object(
            self._request("POST", "/issue", json={"fields": fields}), "issue"
        )

    def update_issue(
        self,
        issue_key: str,
        *,
        summary: Any = _UNSET,
        description: Any = _UNSET,
        assignee_account_id: Any = _UNSET,
        labels: Any = _UNSET,
    ) -> dict[str, Any]:
        """Update fields on an existing Jira issue."""
        fields: dict[str, Any] = {}
        if summary is not _UNSET:
            fields["summary"] = summary
        if description is not _UNSET:
            fields["description"] = (
                None if description is None else self._text_document_payload(description)
            )
        if assignee_account_id is not _UNSET:
            fields["assignee"] = (
                None
                if assignee_account_id is None
                else self._user_identity_payload(assignee_account_id)
            )
        if labels is not _UNSET:
            fields["labels"] = labels
        if not fields:
            raise ValueError("Jira updateIssue requires at least one field to update")
        self._request("PUT", f"/issue/{issue_key}", json={"fields": fields}, expect_json=False)
        return self.get_issue(issue_key)

    def delete_issue(self, issue_key: str) -> bool:
        """Delete a Jira issue."""
        self._request("DELETE", f"/issue/{issue_key}", expect_json=False)
        return True

    def get_issue_changelog(
        self, issue_key: str, limit: int = 50, start_at: int = 0
    ) -> dict[str, Any]:
        """Return the changelog entries for a Jira issue."""
        normalized_limit = self._normalize_limit(limit)
        offset = max(start_at, 0)
        if self._api_version == "2":
            return self._get_issue_changelog_v2(issue_key, normalized_limit, offset)
        payload = self._request(
            "GET",
            f"/issue/{issue_key}/changelog",
            params={"maxResults": normalized_limit, "startAt": offset},
        )
        return self._expect_object(payload, "issue.changelog")

    def notify_issue(
        self,
        issue_key: str,
        *,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        to: dict[str, Any] | None = None,
    ) -> bool:
        """Send a Jira issue notification."""
        payload: dict[str, Any] = {
            "subject": subject,
            "textBody": text_body,
            "to": to or {"assignee": True},
        }
        if html_body:
            payload["htmlBody"] = html_body
        self._request("POST", f"/issue/{issue_key}/notify", json=payload, expect_json=False)
        return True

    def list_comments(self, issue_key: str, limit: int = 50, start_at: int = 0) -> dict[str, Any]:
        """List comments on a Jira issue."""
        payload = self._request(
            "GET",
            f"/issue/{issue_key}/comment",
            params={"maxResults": self._normalize_limit(limit), "startAt": max(start_at, 0)},
        )
        return self._expect_object(payload, "issue.comments")

    def create_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        """Add a comment to a Jira issue."""
        payload = self._request(
            "POST",
            f"/issue/{issue_key}/comment",
            json={"body": self._text_document_payload(body)},
        )
        return self._expect_object(payload, "comment")

    def get_comment(self, issue_key: str, comment_id: str) -> dict[str, Any]:
        """Fetch one comment on a Jira issue."""
        payload = self._request("GET", f"/issue/{issue_key}/comment/{comment_id}")
        return self._expect_object(payload, "comment")

    def update_comment(self, issue_key: str, comment_id: str, body: str) -> dict[str, Any]:
        """Update a comment on a Jira issue."""
        payload = self._request(
            "PUT",
            f"/issue/{issue_key}/comment/{comment_id}",
            json={"body": self._text_document_payload(body)},
        )
        return self._expect_object(payload, "comment")

    def delete_comment(self, issue_key: str, comment_id: str) -> bool:
        """Delete a comment from a Jira issue."""
        self._request("DELETE", f"/issue/{issue_key}/comment/{comment_id}", expect_json=False)
        return True

    def list_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """List available transitions for a Jira issue."""
        payload = self._expect_object(
            self._request("GET", f"/issue/{issue_key}/transitions"),
            "issue.transitions",
        )
        transitions = payload.get("transitions")
        if not isinstance(transitions, list):
            raise ValueError("Jira API returned an invalid transitions payload")
        return [transition for transition in transitions if isinstance(transition, dict)]

    def transition_issue(self, issue_key: str, transition_id: str) -> dict[str, Any]:
        """Transition a Jira issue using a transition ID."""
        self._request(
            "POST",
            f"/issue/{issue_key}/transitions",
            json={"transition": {"id": transition_id}},
            expect_json=False,
        )
        issue = self.get_issue(issue_key)
        return {"transitionId": transition_id, "issue": issue}

    def add_attachment(
        self,
        issue_key: str,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add a file attachment to a Jira issue."""
        payload = self._request(
            "POST",
            f"/issue/{issue_key}/attachments",
            files={"file": (filename, content, mime_type or "application/octet-stream")},
            headers={"X-Atlassian-Token": "no-check"},
        )
        if not isinstance(payload, list):
            raise ValueError("Jira API returned an invalid attachment upload payload")
        return [attachment for attachment in payload if isinstance(attachment, dict)]

    def get_attachment(self, attachment_id: str) -> dict[str, Any]:
        """Fetch one Jira attachment metadata object."""
        payload = self._request("GET", f"/attachment/{attachment_id}")
        return self._expect_object(payload, "attachment")

    def list_attachments(
        self, issue_key: str, limit: int = 50, start_at: int = 0
    ) -> dict[str, Any]:
        """List attachment metadata for a Jira issue."""
        issue = self.get_issue_with_fields(issue_key, ["attachment"])
        fields = issue.get("fields")
        attachments = fields.get("attachment") if isinstance(fields, dict) else []
        if not isinstance(attachments, list):
            raise ValueError("Jira API returned an invalid issue attachment payload")
        normalized = [attachment for attachment in attachments if isinstance(attachment, dict)]
        normalized_limit = self._normalize_limit(limit)
        offset = max(start_at, 0)
        page = normalized[offset : offset + normalized_limit]
        total = len(normalized)
        return {
            "attachments": page,
            "startAt": offset,
            "maxResults": normalized_limit,
            "total": total,
            "isLast": offset + normalized_limit >= total,
        }

    def delete_attachment(self, attachment_id: str) -> bool:
        """Delete a Jira attachment by ID."""
        self._request("DELETE", f"/attachment/{attachment_id}", expect_json=False)
        return True

    def download_attachment(self, content_url: str) -> bytes:
        """Download raw attachment content from Jira's content URL."""
        payload = self._request_absolute(
            "GET",
            content_url,
            headers={"Accept": "*/*"},
            expect_json=False,
        )
        if not isinstance(payload, bytes):
            raise ValueError("Jira API returned invalid attachment content")
        return payload

    def get_user(self, account_id: str) -> dict[str, Any]:
        """Fetch a Jira user by account ID or Data Center username."""
        payload = self._request("GET", "/user", params=self._user_identity_params(account_id))
        return self._expect_object(payload, "user")

    def create_user(
        self,
        email_address: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
        products: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a Jira user."""
        payload: dict[str, Any] = {"emailAddress": email_address}
        if self._is_data_center:
            payload["name"] = username or email_address
        if display_name:
            payload["displayName"] = display_name
        if products and not self._is_data_center:
            payload["products"] = products
        result = self._request("POST", "/user", json=payload)
        return self._expect_object(result, "user")

    def delete_user(self, account_id: str) -> bool:
        """Delete a Jira user by account ID or Data Center username."""
        self._request(
            "DELETE", "/user", params=self._user_identity_params(account_id), expect_json=False
        )
        return True

    def get_issue_with_fields(self, issue_key: str, fields: list[str]) -> dict[str, Any]:
        """Fetch one Jira issue with a restricted fields list."""
        payload = self._request(
            "GET",
            f"/issue/{issue_key}",
            params={"fields": ",".join(fields)},
        )
        return self._expect_object(payload, "issue")

    def _get_issue_changelog_v2(self, issue_key: str, limit: int, start_at: int) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/issue/{issue_key}",
            params={"expand": "changelog", "fields": "none"},
        )
        issue = self._expect_object(payload, "issue")
        changelog = issue.get("changelog")
        if not isinstance(changelog, dict):
            raise ValueError("Jira API returned an invalid issue.changelog payload")
        histories = changelog.get("histories")
        if not isinstance(histories, list):
            raise ValueError("Jira API returned an invalid issue.changelog payload")
        normalized = [history for history in histories if isinstance(history, dict)]
        total = int(changelog.get("total") or len(normalized))
        page = normalized[start_at : start_at + limit]
        return {
            "histories": page,
            "startAt": start_at,
            "maxResults": limit,
            "total": total,
            "isLast": start_at + limit >= total,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        return self._request_absolute(
            method,
            self._url(path),
            params=params,
            json=json,
            files=files,
            headers=headers,
            expect_json=expect_json,
        )

    def _request_absolute(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        email = str(self._config.get("email", "") or "").strip()
        api_token = str(
            self._config.get("api_token", "") or self._config.get("api_key", "") or ""
        ).strip()
        if not email or not api_token:
            raise ValueError("Jira credential requires email and api_token")
        request_headers = {"Accept": "application/json"}
        if files is None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        try:
            response = self._client.request(
                method,
                url,
                params=params,
                json=json,
                files=files,
                auth=(email, api_token),
                headers=request_headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._truncate_error_detail(response.text)
            raise ValueError(
                f"Jira API request failed with status {response.status_code}: {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"Jira API request failed: {exc}") from exc
        if not expect_json:
            return response.content
        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("Jira API returned non-JSON response") from exc
        return payload

    def _url(self, path: str) -> str:
        return urljoin(f"{self._base_url}/rest/api/{self._api_version}/", path.lstrip("/"))

    @property
    def _is_data_center(self) -> bool:
        return self._deployment == "data_center"

    def _user_identity_payload(self, value: str) -> dict[str, str]:
        if self._is_data_center:
            return {"name": value}
        return {"accountId": value}

    def _user_identity_params(self, value: str) -> dict[str, str]:
        if self._is_data_center:
            return {"username": value}
        return {"accountId": value}

    def _text_document_payload(self, text: str) -> str | dict[str, Any]:
        if self._api_version == "2":
            return text
        return self._adf_text_document(text)

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("Jira credential requires base_url")
        return normalized

    @staticmethod
    def _normalize_deployment(config: dict[str, Any]) -> str:
        raw_deployment = str(config.get("deployment", "") or "").strip().lower().replace("-", "_")
        if raw_deployment in {"data_center", "datacenter", "server", "self_hosted"}:
            return "data_center"
        if raw_deployment == "cloud":
            return "cloud"
        if not raw_deployment and str(config.get("api_version", "") or "").strip() == "2":
            return "data_center"
        return _DEFAULT_DEPLOYMENT

    @staticmethod
    def _normalize_api_version(config: dict[str, Any], deployment: str) -> str:
        if deployment == "data_center":
            return "2"
        return str(config.get("api_version") or _DEFAULT_API_VERSION).strip()

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        return max(1, min(int(limit), 100))

    @staticmethod
    def _expect_object(payload: Any, label: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError(f"Jira API returned an invalid {label} payload")
        return payload

    @staticmethod
    def _expect_project_list(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise ValueError("Jira API returned an invalid project list payload")
        return [project for project in payload if isinstance(project, dict)]

    @staticmethod
    def _adf_text_document(text: str) -> dict[str, Any]:
        lines = text.split("\n")
        content: list[dict[str, Any]] = []
        for line in lines:
            paragraph: dict[str, Any] = {"type": "paragraph"}
            if line:
                paragraph["content"] = [{"type": "text", "text": line}]
            else:
                paragraph["content"] = []
            content.append(paragraph)
        if not content:
            content = [{"type": "paragraph", "content": []}]
        return {"type": "doc", "version": 1, "content": content}

    @staticmethod
    def _truncate_error_detail(detail: str) -> str:
        normalized = detail.strip()
        if len(normalized) <= _MAX_ERROR_DETAIL_CHARS:
            return normalized
        return f"{normalized[:_MAX_ERROR_DETAIL_CHARS]}..."
