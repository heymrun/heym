import base64
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.http_identity import merge_outbound_headers

GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubService:
    """Small REST client for GitHub and GitHub Enterprise API operations."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(
            headers=merge_outbound_headers(
                {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
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

    def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch repository metadata."""
        return self._request_json("GET", f"/repos/{owner}/{repo}")

    def get_repository_license(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch the detected repository license and decoded file content."""
        response = self._request_json("GET", f"/repos/{owner}/{repo}/license")
        if not isinstance(response, dict):
            raise ValueError("GitHub getRepositoryLicense returned an unexpected response")
        decoded_content: str | None = None
        if str(response.get("encoding") or "").lower() == "base64" and response.get("content"):
            try:
                decoded_content = base64.b64decode(str(response["content"]).encode("utf-8")).decode(
                    "utf-8"
                )
            except Exception:
                decoded_content = None
        return {**response, "decoded_content": decoded_content}

    def get_repository_profile(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch repository community profile metrics."""
        response = self._request_json("GET", f"/repos/{owner}/{repo}/community/profile")
        if not isinstance(response, dict):
            raise ValueError("GitHub getRepositoryProfile returned an unexpected response")
        return response

    def list_popular_paths(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """List the repository's popular content paths."""
        response = self._request_json("GET", f"/repos/{owner}/{repo}/traffic/popular/paths")
        return response if isinstance(response, list) else []

    def list_referrers(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """List the repository's top referring domains."""
        response = self._request_json("GET", f"/repos/{owner}/{repo}/traffic/popular/referrers")
        return response if isinstance(response, list) else []

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        """Fetch one issue by number."""
        return self._request_json("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

    def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 30,
        assignee: str | None = None,
        creator: str | None = None,
        mentioned: str | None = None,
        labels: str | None = None,
        since: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
    ) -> list[dict[str, Any]]:
        """List repository issues."""
        params: dict[str, Any] = {
            "state": state or "open",
            "per_page": max(1, min(per_page, 100)),
        }
        for key, value in {
            "assignee": assignee,
            "creator": creator,
            "mentioned": mentioned,
            "labels": labels,
            "since": since,
            "sort": sort,
            "direction": direction,
        }.items():
            if value:
                params[key] = value
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params=params,
        )
        if not isinstance(response, list):
            return []
        return [
            item
            for item in response
            if isinstance(item, dict) and not isinstance(item.get("pull_request"), dict)
        ]

    def create_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Create an issue comment."""
        return self._request_json(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    def lock_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        lock_reason: str | None = None,
    ) -> dict[str, Any]:
        """Lock a repository issue."""
        payload = {"lock_reason": lock_reason} if lock_reason else None
        self._request_no_content(
            "PUT",
            f"/repos/{owner}/{repo}/issues/{issue_number}/lock",
            json=payload,
            success_codes=(204,),
        )
        return {"issue_number": issue_number, "locked": True, "lock_reason": lock_reason}

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub issue."""
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return self._request_json("POST", f"/repos/{owner}/{repo}/issues", json=payload)

    def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        state_reason: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing GitHub issue."""
        payload: dict[str, Any] = {}
        if title is not None and title != "":
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state:
            payload["state"] = state
        if state_reason:
            payload["state_reason"] = state_reason
        if labels is not None:
            payload["labels"] = labels
        if assignees is not None:
            payload["assignees"] = assignees
        if not payload:
            raise ValueError("GitHub updateIssue requires at least one field to update")
        return self._request_json(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json=payload,
        )

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 30,
        sort: str | None = None,
        direction: str | None = None,
    ) -> list[dict[str, Any]]:
        """List repository pull requests."""
        params: dict[str, Any] = {
            "state": state or "open",
            "per_page": max(1, min(per_page, 100)),
        }
        if sort:
            params["sort"] = sort
        if direction:
            params["direction"] = direction
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params=params,
        )
        return response if isinstance(response, list) else []

    def get_repository_issues(
        self,
        owner: str,
        repo: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Get repository issues using the repository-resource action semantics."""
        return self.list_issues(owner, repo, **kwargs)

    def get_repository_pull_requests(
        self,
        owner: str,
        repo: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Get repository pull requests using the repository-resource action semantics."""
        return self.list_pull_requests(owner, repo, **kwargs)

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a pull request."""
        payload: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
        }
        if body:
            payload["body"] = body
        return self._request_json("POST", f"/repos/{owner}/{repo}/pulls", json=payload)

    def get_review(
        self,
        owner: str,
        repo: str,
        pull_request_number: int,
        review_id: int,
    ) -> dict[str, Any]:
        """Fetch one pull request review."""
        return self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_request_number}/reviews/{review_id}",
        )

    def list_reviews(
        self,
        owner: str,
        repo: str,
        pull_request_number: int,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List reviews for a pull request."""
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_request_number}/reviews",
            params={"per_page": max(1, min(per_page, 100))},
        )
        return response if isinstance(response, list) else []

    def create_review(
        self,
        owner: str,
        repo: str,
        pull_request_number: int,
        event: str,
        body: str | None = None,
        commit_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a pull request review."""
        payload: dict[str, Any] = {"event": event}
        if body is not None:
            payload["body"] = body
        if commit_id:
            payload["commit_id"] = commit_id
        return self._request_json(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_request_number}/reviews",
            json=payload,
        )

    def update_review(
        self,
        owner: str,
        repo: str,
        pull_request_number: int,
        review_id: int,
        body: str,
    ) -> dict[str, Any]:
        """Update a pull request review body."""
        return self._request_json(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pull_request_number}/reviews/{review_id}",
            json={"body": body},
        )

    def list_releases(
        self,
        owner: str,
        repo: str,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List repository releases."""
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/releases",
            params={"per_page": max(1, min(per_page, 100))},
        )
        return response if isinstance(response, list) else []

    def get_release(self, owner: str, repo: str, release_id: int) -> dict[str, Any]:
        """Fetch a release by id."""
        return self._request_json("GET", f"/repos/{owner}/{repo}/releases/{release_id}")

    def create_release(
        self,
        owner: str,
        repo: str,
        tag_name: str,
        name: str | None = None,
        body: str | None = None,
        target_commitish: str | None = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        """Create a release."""
        payload: dict[str, Any] = {
            "tag_name": tag_name,
            "draft": draft,
            "prerelease": prerelease,
        }
        if name:
            payload["name"] = name
        if body:
            payload["body"] = body
        if target_commitish:
            payload["target_commitish"] = target_commitish
        return self._request_json("POST", f"/repos/{owner}/{repo}/releases", json=payload)

    def update_release(
        self,
        owner: str,
        repo: str,
        release_id: int,
        tag_name: str | None = None,
        name: str | None = None,
        body: str | None = None,
        target_commitish: str | None = None,
        draft: bool | None = None,
        prerelease: bool | None = None,
    ) -> dict[str, Any]:
        """Update a release."""
        payload: dict[str, Any] = {}
        if tag_name:
            payload["tag_name"] = tag_name
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["body"] = body
        if target_commitish:
            payload["target_commitish"] = target_commitish
        if draft is not None:
            payload["draft"] = draft
        if prerelease is not None:
            payload["prerelease"] = prerelease
        if not payload:
            raise ValueError("GitHub updateRelease requires at least one field to update")
        return self._request_json(
            "PATCH", f"/repos/{owner}/{repo}/releases/{release_id}", json=payload
        )

    def delete_release(self, owner: str, repo: str, release_id: int) -> dict[str, Any]:
        """Delete a release by id."""
        self._request_no_content(
            "DELETE",
            f"/repos/{owner}/{repo}/releases/{release_id}",
            success_codes=(204,),
        )
        return {"release_id": release_id, "deleted": True}

    def list_workflows(
        self,
        owner: str,
        repo: str,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List GitHub Actions workflows for a repository."""
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/actions/workflows",
            params={"per_page": max(1, min(per_page, 100))},
        )
        if isinstance(response, dict):
            workflows = response.get("workflows")
            return workflows if isinstance(workflows, list) else []
        return []

    def get_workflow(self, owner: str, repo: str, workflow_id: str) -> dict[str, Any]:
        """Fetch a workflow by numeric id or file name."""
        return self._request_json("GET", f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}")

    def enable_workflow(self, owner: str, repo: str, workflow_id: str) -> dict[str, Any]:
        """Enable a GitHub Actions workflow."""
        self._request_no_content(
            "PUT",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable",
            success_codes=(204,),
        )
        return {"workflow_id": workflow_id, "enabled": True}

    def disable_workflow(self, owner: str, repo: str, workflow_id: str) -> dict[str, Any]:
        """Disable a GitHub Actions workflow."""
        self._request_no_content(
            "PUT",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/disable",
            success_codes=(204,),
        )
        return {"workflow_id": workflow_id, "disabled": True}

    def get_workflow_usage(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
    ) -> dict[str, Any]:
        """Fetch billable GitHub Actions usage for one workflow."""
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/timing",
        )
        if not isinstance(response, dict):
            raise ValueError("GitHub getWorkflowUsage returned an unexpected response")
        return response

    def dispatch_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch a workflow run."""
        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        url = f"{self._base_url()}/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
        response = self._client.request(
            "POST",
            url,
            json=payload,
            headers=self._auth_headers(),
        )
        if response.status_code not in (200, 204):
            raise ValueError(self._build_error_message(response))
        result: dict[str, Any] = {
            "workflow_id": workflow_id,
            "ref": ref,
            "inputs": inputs or {},
            "dispatched": True,
        }
        if response.status_code == 200:
            try:
                response_data = response.json()
            except ValueError as exc:
                raise ValueError("GitHub API returned non-JSON dispatch response") from exc
            if isinstance(response_data, dict):
                result.update(response_data)
        return result

    def get_workflow_run(
        self,
        owner: str,
        repo: str,
        run_id: int,
    ) -> dict[str, Any]:
        """Fetch one GitHub Actions workflow run."""
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}",
        )
        if not isinstance(response, dict):
            raise ValueError("GitHub getWorkflowRun returned an unexpected response")
        return response

    def list_workflow_runs(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List recent workflow-dispatch runs for one workflow."""
        response = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs",
            params={
                "event": "workflow_dispatch",
                "per_page": max(1, min(per_page, 100)),
            },
        )
        if not isinstance(response, dict):
            return []
        workflow_runs = response.get("workflow_runs")
        return workflow_runs if isinstance(workflow_runs, list) else []

    @staticmethod
    def _created_at_timestamp(workflow_run: dict[str, Any]) -> float | None:
        created_at = workflow_run.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            return None
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    def _find_dispatched_workflow_run(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        dispatched_at: float,
    ) -> dict[str, Any] | None:
        workflow_runs = self.list_workflow_runs(owner, repo, workflow_id, per_page=100)
        candidates: list[dict[str, Any]] = []
        for workflow_run in workflow_runs:
            head_branch = str(workflow_run.get("head_branch") or "")
            if head_branch and head_branch != ref:
                continue
            created_at = self._created_at_timestamp(workflow_run)
            if created_at is not None and created_at < dispatched_at - 1:
                continue
            candidates.append(workflow_run)
        if not candidates:
            return None
        return max(candidates, key=lambda workflow_run: int(workflow_run.get("id") or 0))

    def dispatch_workflow_and_wait(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, Any] | None = None,
        timeout_seconds: int = 600,
        poll_interval_seconds: float = 5.0,
    ) -> dict[str, Any]:
        """Dispatch a workflow and poll its run until completion."""
        dispatched_at = time.time()
        dispatch_result = self.dispatch_workflow(owner, repo, workflow_id, ref, inputs=inputs)
        run_id_value = dispatch_result.get("workflow_run_id")
        timeout = max(1, timeout_seconds)
        interval = max(0.1, poll_interval_seconds)
        deadline = time.monotonic() + timeout
        workflow_run: dict[str, Any] | None = None
        if run_id_value is None:
            while workflow_run is None:
                workflow_run = self._find_dispatched_workflow_run(
                    owner,
                    repo,
                    workflow_id,
                    ref,
                    dispatched_at,
                )
                if workflow_run is not None:
                    run_id_value = workflow_run.get("id")
                    break
                if time.monotonic() >= deadline:
                    raise ValueError(
                        "GitHub dispatched the workflow but no matching workflow run "
                        f"appeared within {timeout} seconds"
                    )
                time.sleep(interval)
        if run_id_value is None:
            raise ValueError("GitHub workflow run response did not include an id")
        run_id = int(run_id_value)
        dispatch_result["workflow_run_id"] = run_id
        while True:
            if workflow_run is None or int(workflow_run.get("id") or 0) != run_id:
                workflow_run = self.get_workflow_run(owner, repo, run_id)
            if str(workflow_run.get("status") or "").lower() == "completed":
                return {
                    **dispatch_result,
                    "completed": True,
                    "workflow_run": workflow_run,
                    "status": workflow_run.get("status"),
                    "conclusion": workflow_run.get("conclusion"),
                }
            if time.monotonic() >= deadline:
                raise ValueError(
                    f"GitHub workflow run {run_id} did not complete within {timeout} seconds"
                )
            time.sleep(interval)
            workflow_run = None

    def get_file(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, Any]:
        """Read a repository file through the contents API."""
        params: dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        data = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/contents/{quote(path.lstrip('/'), safe='/')}",
            params=params or None,
        )
        if not isinstance(data, dict):
            raise ValueError("GitHub getFile returned an unexpected response")

        encoding = str(data.get("encoding") or "").lower()
        decoded_text: str | None = None
        if encoding == "base64" and data.get("content"):
            try:
                decoded_text = base64.b64decode(str(data["content"]).encode("utf-8")).decode(
                    "utf-8"
                )
            except Exception:
                decoded_text = None

        return {
            "name": data.get("name"),
            "path": data.get("path"),
            "sha": data.get("sha"),
            "size": data.get("size"),
            "url": data.get("html_url") or data.get("download_url") or data.get("url"),
            "content": decoded_text,
            "encoding": data.get("encoding"),
        }

    def list_files(
        self,
        owner: str,
        repo: str,
        path: str = "",
        ref: str | None = None,
    ) -> dict[str, Any]:
        """List files inside a repository directory via the contents API."""
        normalized_path = quote(path.lstrip("/"), safe="/")
        endpoint = f"/repos/{owner}/{repo}/contents"
        if normalized_path:
            endpoint = f"{endpoint}/{normalized_path}"
        params: dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        data = self._request_json("GET", endpoint, params=params or None)
        if not isinstance(data, list):
            raise ValueError("GitHub listFiles expects a directory path")
        items: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "type": item.get("type"),
                    "sha": item.get("sha"),
                    "size": item.get("size"),
                    "url": item.get("html_url") or item.get("download_url") or item.get("url"),
                }
            )
        return {"path": path or "", "items": items, "count": len(items)}

    def upsert_file(
        self,
        owner: str,
        repo: str,
        path: str,
        message: str,
        content: str,
        branch: str | None = None,
        sha: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a repository file."""
        normalized_path = quote(path.lstrip("/"), safe="/")
        target_sha = sha.strip() if sha else ""
        if not target_sha:
            try:
                existing = self._request_json(
                    "GET",
                    f"/repos/{owner}/{repo}/contents/{normalized_path}",
                    params={"ref": branch} if branch else None,
                )
                if isinstance(existing, dict):
                    target_sha = str(existing.get("sha") or "").strip()
            except ValueError as exc:
                if "404" not in str(exc):
                    raise

        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }
        if branch:
            payload["branch"] = branch
        if target_sha:
            payload["sha"] = target_sha

        data = self._request_json(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{normalized_path}",
            json=payload,
        )
        if not isinstance(data, dict):
            raise ValueError("GitHub upsertFile returned an unexpected response")

        content_data = data.get("content") if isinstance(data.get("content"), dict) else {}
        commit_data = data.get("commit") if isinstance(data.get("commit"), dict) else {}
        return {
            "path": content_data.get("path") or path,
            "sha": content_data.get("sha"),
            "commit_sha": commit_data.get("sha"),
            "url": content_data.get("html_url") or content_data.get("git_url"),
            "created": not bool(target_sha),
        }

    def delete_file(
        self,
        owner: str,
        repo: str,
        path: str,
        message: str,
        branch: str | None = None,
        sha: str | None = None,
    ) -> dict[str, Any]:
        """Delete a repository file."""
        normalized_path = quote(path.lstrip("/"), safe="/")
        target_sha = sha.strip() if sha else ""
        if not target_sha:
            existing = self._request_json(
                "GET",
                f"/repos/{owner}/{repo}/contents/{normalized_path}",
                params={"ref": branch} if branch else None,
            )
            if not isinstance(existing, dict):
                raise ValueError("GitHub deleteFile could not resolve the existing file SHA")
            target_sha = str(existing.get("sha") or "").strip()
        if not target_sha:
            raise ValueError("GitHub deleteFile requires a file SHA")

        payload: dict[str, Any] = {"message": message, "sha": target_sha}
        if branch:
            payload["branch"] = branch
        data = self._request_json(
            "DELETE",
            f"/repos/{owner}/{repo}/contents/{normalized_path}",
            json=payload,
        )
        if not isinstance(data, dict):
            raise ValueError("GitHub deleteFile returned an unexpected response")

        commit_data = data.get("commit") if isinstance(data.get("commit"), dict) else {}
        return {
            "path": path,
            "sha": target_sha,
            "commit_sha": commit_data.get("sha"),
            "deleted": True,
        }

    def list_organization_repositories(
        self,
        organization: str,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List repositories for an organization."""
        response = self._request_json(
            "GET",
            f"/orgs/{organization}/repos",
            params={"per_page": max(1, min(per_page, 100))},
        )
        return response if isinstance(response, list) else []

    def list_user_repositories(
        self,
        username: str,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List repositories for a user."""
        response = self._request_json(
            "GET",
            f"/users/{username}/repos",
            params={"per_page": max(1, min(per_page, 100))},
        )
        return response if isinstance(response, list) else []

    def get_user_repositories(
        self,
        username: str,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """Get repositories owned by a user."""
        return self.list_user_repositories(username, per_page=per_page)

    def get_user_issues(
        self,
        state: str = "open",
        per_page: int = 30,
        mentioned: str | None = None,
        labels: str | None = None,
        since: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get issues assigned to or mentioning the authenticated user."""
        params: dict[str, Any] = {
            "filter": "mentioned" if mentioned else "assigned",
            "state": state or "open",
            "per_page": max(1, min(per_page, 100)),
        }
        for key, value in {
            "labels": labels,
            "since": since,
            "sort": sort,
            "direction": direction,
        }.items():
            if value:
                params[key] = value
        response = self._request_json("GET", "/issues", params=params)
        return response if isinstance(response, list) else []

    def invite_user(self, organization: str, email: str) -> dict[str, Any]:
        """Invite a user to an organization by email."""
        response = self._request_json(
            "POST",
            f"/orgs/{organization}/invitations",
            json={"email": email},
        )
        if not isinstance(response, dict):
            raise ValueError("GitHub inviteUser returned an unexpected response")
        return response

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        url = f"{self._base_url()}{path}"
        response = self._client.request(
            method,
            url,
            params=params,
            json=json,
            headers=self._auth_headers(),
        )
        if response.status_code >= 400:
            raise ValueError(self._build_error_message(response))
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError("GitHub API returned non-JSON response") from exc

    def _request_no_content(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        success_codes: tuple[int, ...] = (204,),
    ) -> None:
        url = f"{self._base_url()}{path}"
        response = self._client.request(
            method,
            url,
            params=params,
            json=json,
            headers=self._auth_headers(),
        )
        if response.status_code not in success_codes:
            raise ValueError(self._build_error_message(response))

    def _base_url(self) -> str:
        raw = str(self._config.get("base_url") or "").strip()
        return raw.rstrip("/") if raw else GITHUB_API_BASE_URL

    def _auth_headers(self) -> dict[str, str]:
        token = str(self._config.get("api_key") or self._config.get("token") or "").strip()
        if not token:
            raise ValueError("GitHub credential requires api_key")
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _build_error_message(response: httpx.Response) -> str:
        prefix = f"GitHub API error ({response.status_code})"
        try:
            data = response.json()
        except ValueError:
            text = response.text.strip()
            return f"{prefix}: {text or 'unknown error'}"

        if isinstance(data, dict):
            message = str(data.get("message") or "").strip()
            errors = data.get("errors")
            if isinstance(errors, list) and errors:
                detail_parts: list[str] = []
                for item in errors:
                    if isinstance(item, dict):
                        detail = str(
                            item.get("message") or item.get("code") or item.get("field") or ""
                        ).strip()
                        if detail:
                            detail_parts.append(detail)
                    elif item:
                        detail_parts.append(str(item))
                if detail_parts:
                    message = (
                        f"{message} ({'; '.join(detail_parts)})"
                        if message
                        else "; ".join(detail_parts)
                    )
            if message:
                return f"{prefix}: {message}"

        return f"{prefix}: unknown error"
