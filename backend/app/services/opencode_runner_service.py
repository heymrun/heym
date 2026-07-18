"""Run the OpenCode Go CLI against a cloned repository.

OpenCode has no built-in OS sandbox (unlike Codex's ``--sandbox``). Isolation is selected by
``HEYM_OPENCODE_CLI_COMMAND``: local dev (``run.sh``) uses the host ``opencode`` binary directly,
while Docker deployments point it at ``heym-opencode-docker``, a wrapper that runs OpenCode inside a
hardened, throwaway sibling container sharing the workspace named volume. Either way, all git/GitHub
work stays host-side and reuses the shared ``coding_agent.pr_publish`` helpers, so the GitHub token
is never placed inside the OpenCode process/container.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.services.coding_agent import pr_publish
from app.services.github_service import GitHubService
from app.services.opencode_catalog import OPENCODE_DEFAULT_MODEL, OPENCODE_ZEN_BASE_URL

_REMOTE_PUBLISH_MODES: frozenset[str] = frozenset(
    {"draft_pr", "open_pr", "commit_push", "direct_commit", "update_existing_pr"}
)
_PR_SCREENSHOT_RELEASE_TAG = "opencode-pr-assets"

_LOCAL_ONLY_RULES = (
    "Apply ALL changes by editing files on disk in the current working directory. Do NOT run git; "
    "do NOT commit, push, or create branches; and do NOT use the GitHub API or any remote tool to "
    "modify the repository — Heym performs every git and GitHub operation after you finish. For "
    "UI/frontend visual changes, save at least one PNG screenshot under a gitignored path such as "
    "`frontend/.e2e-artifacts/`; Heym uploads those images onto the pull request afterward."
)


@dataclass(frozen=True)
class OpenCodeRunRequest:
    """Input for an OpenCode CLI run inside a cloned repository workspace."""

    repository_url: str
    base_branch: str
    task_prompt: str
    branch_name: str
    publish_mode: str
    setup_command: str
    timeout_seconds: float
    api_key: str
    base_url: str
    github_config: dict
    model: str = ""
    variant: str = ""


@dataclass
class OpenCodeRunResult:
    """Normalized OpenCode node output."""

    status: str = "completed"
    summary: str = ""
    validation: str = ""
    pull_request_title: str = ""
    pull_request_body: str = ""
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    workspace_path: str | None = None
    branch_name: str = ""
    pull_request_url: str | None = None
    pushed_branch: str = ""
    raw_events: list[dict] = field(default_factory=list)

    def to_output(self) -> dict:
        # No workspacePath in output: there is no resume path (lean HITL) and the handler cleans
        # up the workspace after building the result.
        output = {
            "status": self.status,
            "summary": self.summary,
            "validation": self.validation,
            "diff": self.diff,
            "changedFiles": self.changed_files,
            "branchName": self.branch_name,
            "pullRequestUrl": self.pull_request_url,
            "pushedBranch": self.pushed_branch,
        }
        return {key: value for key, value in output.items() if value not in (None, "", [])}


class OpenCodeRunnerService:
    """Run the OpenCode CLI against a cloned repo; git/publish stays host-side.

    Execution isolation is chosen by ``HEYM_OPENCODE_CLI_COMMAND`` (like the Codex node):

    * ``run.sh`` / local dev leaves it at the default ``opencode`` — OpenCode runs as a host
      subprocess against the cloned workspace.
    * Docker deployments (``deploy.sh`` / the single GHCR image) set it to
      ``/usr/local/bin/heym-opencode-docker``, a wrapper that runs OpenCode inside a hardened,
      throwaway sibling container sharing the workspace named volume.

    The runner itself is sandbox-agnostic: it clones the repo, writes the OpenCode config/auth into a
    per-run home directory on the workspace volume, then execs ``<cli_command> run …``.
    """

    def __init__(
        self,
        cli_command: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self.cli_command = cli_command or settings.opencode_cli_command
        self.workspace_root = Path(workspace_root or settings.opencode_workspace_dir)

    # --- auth / config ---
    def _resolve_model(self, model: str) -> str:
        return model.strip() or OPENCODE_DEFAULT_MODEL

    def _write_opencode_config(
        self, home: Path, *, api_key: str, base_url: str, model: str
    ) -> None:
        data_dir = home / ".local" / "share" / "opencode"
        config_dir = home / ".config" / "opencode"
        data_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        auth_path = data_dir / "auth.json"
        auth_path.write_text(json.dumps({"opencode": {"type": "api", "key": api_key}}))
        auth_path.chmod(0o600)
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": model,
            "permission": {"edit": "allow", "bash": "allow", "webfetch": "allow"},
            "provider": {
                "opencode": {
                    "options": {
                        "baseURL": base_url or OPENCODE_ZEN_BASE_URL,
                        "apiKey": api_key,
                    }
                }
            },
        }
        config_path = config_dir / "opencode.json"
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)

    # --- output parsing ---
    def parse_events(self, stdout: str) -> OpenCodeRunResult:
        events: list[dict] = []
        summary = ""
        for raw in (stdout or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            text = self._event_assistant_text(event)
            if text:
                summary = text
        if not summary:
            summary = "OpenCode completed without a final assistant message."
        return OpenCodeRunResult(status="completed", summary=summary, raw_events=events)

    @staticmethod
    def _event_assistant_text(event: dict) -> str:
        role = str(event.get("role") or (event.get("message") or {}).get("role") or "")
        if role and role != "assistant":
            return ""
        for key in ("text", "content"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            return part["text"].strip()
        return ""

    # --- git seam (host-side) ---
    @staticmethod
    def _safe_env() -> dict[str, str]:
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        env.pop("CODEX_ACCESS_TOKEN", None)
        return env

    def _run_command(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        timeout_seconds: float = 600,
        env: dict[str, str] | None = None,
        sensitive_values: list[object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                cmd,
                cwd=cwd,
                env=env if env is not None else self._safe_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=True,
            )
        except FileNotFoundError as exc:
            binary = cmd[0] if cmd else "command"
            raise ValueError(f"'{binary}' is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Command timed out after {timeout_seconds:.0f} seconds") from exc
        except subprocess.CalledProcessError as exc:
            values = [str(v) for v in (sensitive_values or []) if str(v)]
            detail = pr_publish.mask_sensitive(exc.stderr or exc.stdout or str(exc), values)
            raise ValueError(detail or "Command failed") from exc

    def _git_output(self, cmd: list[str], workspace: Path) -> str:
        try:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                env=self._safe_env(),
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return completed.stdout

    def _changed_files(self, workspace: Path) -> list[str]:
        output = self._git_output(["git", "status", "--short"], workspace)
        return [line[3:].strip() for line in output.splitlines() if line.strip()]

    def _clone_branch(self, workspace: Path, request: OpenCodeRunRequest, branch: str) -> None:
        clone_url = pr_publish.clone_url_with_token(request.repository_url, request.github_config)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._run_command(
            ["git", "clone", "--branch", branch, "--single-branch", clone_url, str(workspace)],
            cwd=self.workspace_root,
            timeout_seconds=request.timeout_seconds,
            sensitive_values=[request.github_config.get("api_key", "")],
        )

    def _current_branch(self, workspace: Path) -> str:
        return self._git_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], workspace).strip()

    # --- run orchestration ---
    def run_task(self, request: OpenCodeRunRequest) -> OpenCodeRunResult:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = (self.workspace_root / str(uuid.uuid4())).resolve()
        home = Path(f"{workspace}.oc-home")
        home.mkdir(parents=True, exist_ok=True)

        clone_branch = (
            request.branch_name
            if request.publish_mode == "update_existing_pr"
            else request.base_branch
        )
        try:
            self._clone_branch(workspace, request, clone_branch)
        except ValueError:
            self._clone_branch(workspace, request, request.base_branch)

        if request.setup_command.strip():
            self._run_command(
                ["/bin/sh", "-lc", request.setup_command],
                cwd=workspace,
                timeout_seconds=min(request.timeout_seconds, 600),
            )

        model = self._resolve_model(request.model)
        self._write_opencode_config(
            home, api_key=request.api_key, base_url=request.base_url, model=model
        )
        stdout = self._exec_opencode(workspace, home, request, model)
        result = self.parse_events(stdout)
        result.workspace_path = str(workspace)
        result.branch_name = request.branch_name
        result.diff = self._git_output(["git", "diff", "--binary"], workspace)
        result.changed_files = self._changed_files(workspace)
        if result.status == "completed" and request.publish_mode in _REMOTE_PUBLISH_MODES:
            self._publish(workspace, request, result)
        return result

    def build_run_command(
        self, model: str, request: OpenCodeRunRequest, workspace: Path
    ) -> list[str]:
        """The ``<cli_command> run …`` argv (host binary locally, docker wrapper in deployments).

        ``--dir`` pins OpenCode to the cloned workspace. Without it OpenCode resolves its project by
        walking up from the process cwd and can edit files in an enclosing repository (e.g. Heym's
        own checkout) instead of the clone — the run then reports success with an empty diff.
        """
        prompt = f"{_LOCAL_ONLY_RULES}\n\nTask:\n{request.task_prompt}"
        cmd = [
            self.cli_command,
            "run",
            "--dir",
            str(workspace),
            "--format",
            "json",
            "--model",
            model,
            "--agent",
            "build",
        ]
        if request.variant.strip():
            cmd.extend(["--variant", request.variant.strip()])
        cmd.append(prompt)
        return cmd

    def _exec_opencode(
        self,
        workspace: Path,
        home: Path,
        request: OpenCodeRunRequest,
        model: str,
    ) -> str:
        # HOME/XDG point at the per-run OpenCode home on the workspace volume. The docker wrapper
        # forwards these into the sibling container; locally OpenCode reads them directly.
        env = self._safe_env()
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_DATA_HOME"] = str(home / ".local" / "share")
        cmd = self.build_run_command(model, request, workspace)
        try:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ValueError(
                "OpenCode CLI is not installed or not on PATH (install 'opencode')"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"OpenCode timed out after {request.timeout_seconds:.0f} seconds"
            ) from exc
        if completed.returncode != 0:
            detail = pr_publish.mask_sensitive(
                completed.stderr or completed.stdout or "OpenCode exec failed", [request.api_key]
            )
            raise ValueError(detail)
        return completed.stdout

    # --- publish (reuses shared pr_publish helpers) ---
    def _publish(
        self, workspace: Path, request: OpenCodeRunRequest, result: OpenCodeRunResult
    ) -> None:
        if not result.changed_files:
            return
        mode = request.publish_mode
        if mode == "direct_commit":
            self._commit_changes(workspace, request.base_branch, result, new_branch=False)
            self._push_branch(workspace, request, request.base_branch)
            result.pushed_branch = request.base_branch
            return
        if mode == "update_existing_pr":
            on_existing = self._current_branch(workspace) == request.branch_name
            self._commit_changes(workspace, request.branch_name, result, new_branch=not on_existing)
            self._push_branch(workspace, request, request.branch_name)
            result.pushed_branch = request.branch_name
            existing_url = self._open_pr_url_for_head(request, request.branch_name)
            if existing_url:
                result.pull_request_url = existing_url
                pr_number = pr_publish.pr_number_from_url(existing_url)
                if pr_number is not None:
                    self._attach_pr_screenshots(workspace, request, result, pr_number)
            else:
                result.pull_request_url = self._create_pr(
                    workspace, request, result, request.branch_name, draft=False
                )
            return

        self._commit_changes(workspace, request.branch_name, result, new_branch=True)
        self._push_branch(workspace, request, request.branch_name)
        result.pushed_branch = request.branch_name
        if mode == "draft_pr":
            result.pull_request_url = self._create_pr(
                workspace, request, result, request.branch_name, draft=True
            )
        elif mode == "open_pr":
            result.pull_request_url = self._create_pr(
                workspace, request, result, request.branch_name, draft=False
            )

    def _commit_changes(
        self,
        workspace: Path,
        branch: str,
        result: OpenCodeRunResult,
        *,
        new_branch: bool,
    ) -> None:
        if new_branch:
            self._run_command(["git", "checkout", "-B", branch], cwd=workspace)
        self._run_command(["git", "add", "-A"], cwd=workspace)
        title = pr_publish.commit_title(
            result.pull_request_title, result.summary, fallback="Apply OpenCode changes"
        )
        commit_cmd = [
            "git",
            "-c",
            f"user.name={settings.opencode_git_author_name}",
            "-c",
            f"user.email={settings.opencode_git_author_email}",
            "commit",
            "-m",
            title,
        ]
        body = pr_publish.commit_body(result.summary, result.validation)
        if body and body != title:
            commit_cmd.extend(["-m", body])
        self._run_command(commit_cmd, cwd=workspace)

    def _push_branch(self, workspace: Path, request: OpenCodeRunRequest, branch: str) -> None:
        remote_url = pr_publish.clone_url_with_token(request.repository_url, request.github_config)
        sensitive_values = [request.github_config.get("api_key", "")]
        self._run_command(["git", "remote", "set-url", "origin", remote_url], cwd=workspace)
        remote_branch = self._git_output(
            ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"], workspace
        )
        if remote_branch.strip():
            try:
                self._run_command(
                    ["git", "pull", "--rebase", "--strategy-option=theirs", "origin", branch],
                    cwd=workspace,
                    sensitive_values=sensitive_values,
                )
            except ValueError as exc:
                try:
                    self._run_command(["git", "rebase", "--abort"], cwd=workspace)
                except ValueError:
                    pass
                raise ValueError(
                    f"Could not synchronize branch '{branch}' with origin before push: {exc}"
                ) from exc
        self._run_command(
            ["git", "push", "-u", "origin", branch],
            cwd=workspace,
            sensitive_values=sensitive_values,
        )

    def _open_pr_url_for_head(self, request: OpenCodeRunRequest, head: str) -> str | None:
        owner, repo = pr_publish.parse_github_owner_repo(request.repository_url)
        gh = GitHubService(request.github_config)
        try:
            pulls = gh.list_pull_requests(owner, repo, state="open", per_page=100)
        finally:
            gh.close()
        for pr in pulls:
            if str((pr.get("head") or {}).get("ref") or "") == head:
                return str(pr.get("html_url") or "").strip() or None
        return None

    def _create_pr(
        self,
        workspace: Path,
        request: OpenCodeRunRequest,
        result: OpenCodeRunResult,
        head: str,
        *,
        draft: bool,
    ) -> str | None:
        owner, repo = pr_publish.parse_github_owner_repo(request.repository_url)
        title = pr_publish.commit_title(
            result.pull_request_title, result.summary, fallback="Apply OpenCode changes"
        )
        pr_body = str(result.pull_request_body or "").strip() or result.summary or None
        gh = GitHubService(request.github_config)
        try:
            pr = gh.create_pull_request(
                owner, repo, title, head, request.base_branch, body=pr_body, draft=draft
            )
        finally:
            gh.close()
        url = str(pr.get("html_url") or "").strip() or None
        pr_number = pr.get("number")
        if url and isinstance(pr_number, int):
            self._attach_pr_screenshots(workspace, request, result, pr_number)
        return url

    def _attach_pr_screenshots(
        self,
        workspace: Path,
        request: OpenCodeRunRequest,
        result: OpenCodeRunResult,
        pr_number: int,
    ) -> None:
        try:
            screenshots = pr_publish.discover_pr_screenshots(workspace, self._git_output)
            if not screenshots:
                return
            owner, repo = pr_publish.parse_github_owner_repo(request.repository_url)
            gh = GitHubService(request.github_config)
            try:
                base_body = (
                    str(result.pull_request_body or "").strip()
                    or str(result.summary or "").strip()
                    or ""
                )
                updated_body = pr_publish.upload_and_inject_screenshots(
                    gh,
                    screenshots=screenshots,
                    owner=owner,
                    repo=repo,
                    base_branch=request.base_branch,
                    pr_number=pr_number,
                    base_body=base_body,
                    release_tag=_PR_SCREENSHOT_RELEASE_TAG,
                    release_name="OpenCode PR screenshots",
                    release_body=(
                        "Shared bucket for Heym OpenCode UI screenshots attached to pull requests. "
                        "Assets are named pr-<number>-… and are not part of source."
                    ),
                )
                if not updated_body:
                    return
                gh.update_issue(owner, repo, pr_number, body=updated_body)
                result.pull_request_body = updated_body
            finally:
                gh.close()
        except Exception:
            # Screenshot attach is best-effort; never fail the publish path for it.
            return

    def cleanup_workspace(self, workspace_path: str | None) -> None:
        if not workspace_path:
            return
        path = Path(workspace_path).resolve()
        root = self.workspace_root.resolve()
        if path == root or root not in path.parents:
            return
        shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(Path(f"{path}.oc-home"), ignore_errors=True)
