from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from app.config import settings
from app.services.github_service import GitHubService

# OpenAI strict structured output requires every property to appear in `required` when
# `additionalProperties` is false; optional fields are expressed as nullable instead.
CODEX_FINAL_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["completed", "needs_input"]},
        "summary": {"type": "string"},
        "question": {"type": ["string", "null"]},
        "validation": {"type": ["string", "null"]},
        "pull_request_title": {"type": ["string", "null"]},
        "pull_request_body": {"type": ["string", "null"]},
    },
    "required": [
        "status",
        "summary",
        "question",
        "validation",
        "pull_request_title",
        "pull_request_body",
    ],
}

# Supported publish modes. ``diff_only`` and ``patch_artifact`` never touch the remote; the others
# commit and push. ``patch_artifact`` storage is handled by the node handler (needs user context).
CODEX_PUBLISH_MODES: frozenset[str] = frozenset(
    {
        "diff_only",
        "draft_pr",
        "open_pr",
        "commit_push",
        "direct_commit",
        "update_existing_pr",
        "patch_artifact",
    }
)
_CODEX_REMOTE_PUBLISH_MODES: frozenset[str] = frozenset(
    {"draft_pr", "open_pr", "commit_push", "direct_commit", "update_existing_pr"}
)

# Codex must only edit files on disk; Heym owns all git/GitHub operations. Codex's own GitHub
# tools/API are network calls that the sandbox blocks, which otherwise makes Codex loop on
# needs_input asking to "approve write tool calls".
_CODEX_LOCAL_ONLY_RULES = (
    "Apply ALL changes by editing files on disk in the current working directory. Do NOT run git; "
    "do NOT commit, push, or create branches; and do NOT use the GitHub API, a GitHub connector, "
    "or any remote/network tool to modify the repository — Heym performs every git and GitHub "
    "operation after you finish. If network access is available, use it only for read-only "
    "downloads or dependency lookups needed to complete the local file edits."
)


@dataclass(frozen=True)
class CodexRunRequest:
    """Input for a Codex CLI run inside a cloned repository workspace."""

    repository_url: str
    base_branch: str
    task_prompt: str
    branch_name: str
    publish_mode: str
    setup_command: str
    timeout_seconds: float
    codex_access_token: str
    github_config: dict
    codex_auth: dict = field(default_factory=dict)
    model: str = ""


@dataclass(frozen=True)
class CodexResumeRequest:
    """Input for resuming a paused Codex CLI thread."""

    answer_text: str
    thread_id: str | None
    workspace_path: str
    branch_name: str
    publish_mode: str
    base_branch: str
    repository_url: str
    codex_access_token: str
    github_config: dict
    timeout_seconds: float
    codex_auth: dict = field(default_factory=dict)
    model: str = ""


@dataclass
class CodexRunResult:
    """Normalized Codex node output."""

    status: str
    summary: str = ""
    question: str = ""
    validation: str = ""
    pull_request_title: str = ""
    pull_request_body: str = ""
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    thread_id: str | None = None
    workspace_path: str | None = None
    branch_name: str = ""
    pull_request_url: str | None = None
    pushed_branch: str = ""
    usage: dict | None = None
    raw_events: list[dict] = field(default_factory=list)

    def to_output(self) -> dict:
        output = {
            "status": self.status,
            "summary": self.summary,
            "question": self.question,
            "validation": self.validation,
            "diff": self.diff,
            "changedFiles": self.changed_files,
            "threadId": self.thread_id,
            "workspacePath": self.workspace_path,
            "branchName": self.branch_name,
            "pullRequestUrl": self.pull_request_url,
            "pushedBranch": self.pushed_branch,
            "usage": self.usage or {},
        }
        return {key: value for key, value in output.items() if value not in (None, "", [])}


class CodexJsonlParser:
    """Parse Codex CLI JSONL output into a stable node result."""

    def parse(self, stdout: str) -> CodexRunResult:
        events: list[dict] = []
        final_payload: dict | None = None
        thread_id: str | None = None
        usage: dict | None = None

        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            thread_id = thread_id or self._find_string_key(
                event,
                {"thread_id", "threadId", "conversation_id", "conversationId", "session_id"},
            )
            usage_candidate = self._find_dict_key(event, {"usage", "token_usage", "tokenUsage"})
            if usage_candidate is not None:
                usage = usage_candidate
            payload = self._extract_final_payload(event)
            if payload is not None:
                final_payload = payload

        if final_payload is None:
            final_payload = self._last_status_payload(events)
        if final_payload is None:
            return CodexRunResult(
                status="completed",
                summary="Codex completed without a structured final payload.",
                thread_id=thread_id,
                usage=usage,
                raw_events=events,
            )

        status = str(final_payload.get("status") or "completed").strip() or "completed"
        if status not in {"completed", "needs_input"}:
            status = "completed"
        return CodexRunResult(
            status=status,
            summary=str(final_payload.get("summary") or "").strip(),
            question=str(final_payload.get("question") or "").strip(),
            validation=str(final_payload.get("validation") or "").strip(),
            pull_request_title=str(final_payload.get("pull_request_title") or "").strip(),
            pull_request_body=str(final_payload.get("pull_request_body") or "").strip(),
            thread_id=thread_id
            or self._find_string_key(
                final_payload,
                {"thread_id", "threadId", "conversation_id", "conversationId", "session_id"},
            ),
            usage=usage,
            raw_events=events,
        )

    def _extract_final_payload(self, event: dict) -> dict | None:
        if str(event.get("status") or "") in {"completed", "needs_input"}:
            return event
        # codex exec emits the schema-conforming output as an agent_message item's `text`,
        # e.g. {"type":"item.completed","item":{"type":"agent_message","text":"{...}"}}.
        item = event.get("item")
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parsed = self._parse_embedded_json(text)
                if parsed is not None and str(parsed.get("status") or "") in {
                    "completed",
                    "needs_input",
                }:
                    return parsed
        for key in ("result", "final", "final_output", "output", "data"):
            value = event.get(key)
            if isinstance(value, dict) and str(value.get("status") or "") in {
                "completed",
                "needs_input",
            }:
                return value
            if isinstance(value, str):
                parsed = self._parse_embedded_json(value)
                if parsed is not None:
                    return parsed
        return None

    def _last_status_payload(self, events: list[dict]) -> dict | None:
        for event in reversed(events):
            payload = self._extract_final_payload(event)
            if payload is not None:
                return payload
        return None

    @staticmethod
    def _parse_embedded_json(value: str) -> dict | None:
        cleaned = value.strip()
        if not cleaned.startswith("{"):
            return None
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _find_string_key(self, value: object, keys: set[str]) -> str | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, str) and item.strip():
                    return item.strip()
                found = self._find_string_key(item, keys)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._find_string_key(item, keys)
                if found:
                    return found
        return None

    def _find_dict_key(self, value: object, keys: set[str]) -> dict | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, dict):
                    return item
                found = self._find_dict_key(item, keys)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._find_dict_key(item, keys)
                if found is not None:
                    return found
        return None


class CodexRunnerService:
    """Run Codex CLI in an isolated workspace using a ChatGPT/Codex access token."""

    def __init__(self, cli_command: str | None = None, workspace_root: str | None = None) -> None:
        self.cli_command = cli_command or settings.codex_cli_command
        self.workspace_root = Path(workspace_root or settings.codex_workspace_dir)
        self.parser = CodexJsonlParser()

    def run_task(self, request: CodexRunRequest) -> CodexRunResult:
        workspace = self._prepare_workspace(request)
        self._authenticate(
            workspace, request.codex_auth, request.codex_access_token, request.timeout_seconds
        )
        if request.setup_command.strip():
            self._run_setup_command(workspace, request.setup_command, request.timeout_seconds)
        prompt = self._build_prompt(request.task_prompt)
        result = self._run_codex_exec(
            workspace=workspace,
            prompt=prompt,
            timeout_seconds=request.timeout_seconds,
            resume_thread_id=None,
            codex_access_token=self._exec_token(request.codex_auth, request.codex_access_token),
            model=request.model,
        )
        return self._finalize_result(result, workspace, request)

    def resume_task(self, request: CodexResumeRequest) -> CodexRunResult:
        workspace = Path(request.workspace_path).resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError("Codex workspace is no longer available")
        # Defense for workspaces created before CODEX_HOME moved out of the repo: keep any stale
        # in-repo scaffolding out of git so a resume never stages/pushes a leftover auth.json.
        self._exclude_runner_files(workspace)
        self._authenticate(
            workspace, request.codex_auth, request.codex_access_token, request.timeout_seconds
        )
        prompt = self._build_resume_prompt(request.answer_text)
        result = self._run_codex_exec(
            workspace=workspace,
            prompt=prompt,
            timeout_seconds=request.timeout_seconds,
            resume_thread_id=request.thread_id,
            codex_access_token=self._exec_token(request.codex_auth, request.codex_access_token),
            model=request.model,
        )
        run_request = CodexRunRequest(
            repository_url=request.repository_url,
            base_branch=request.base_branch,
            task_prompt=request.answer_text,
            branch_name=request.branch_name,
            publish_mode=request.publish_mode,
            setup_command="",
            timeout_seconds=request.timeout_seconds,
            codex_access_token=request.codex_access_token,
            github_config=request.github_config,
            codex_auth=request.codex_auth,
            model=request.model,
        )
        return self._finalize_result(result, workspace, run_request)

    def _prepare_workspace(self, request: CodexRunRequest) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = (self.workspace_root / str(uuid.uuid4())).resolve()
        # ``update_existing_pr`` clones the existing PR branch so Codex works on top of it; if that
        # branch does not exist yet it falls back to the base branch and creates it.
        if request.publish_mode == "update_existing_pr":
            try:
                self._clone_branch(workspace, request, request.branch_name)
                self._exclude_runner_files(workspace)
                return workspace
            except ValueError:
                shutil.rmtree(workspace, ignore_errors=True)
        self._clone_branch(workspace, request, request.base_branch)
        self._exclude_runner_files(workspace)
        return workspace

    def _clone_branch(self, workspace: Path, request: CodexRunRequest, branch: str) -> None:
        clone_url = self._clone_url_with_token(request.repository_url, request.github_config)
        self._run_command(
            [
                "git",
                "clone",
                "--branch",
                branch,
                "--single-branch",
                clone_url,
                str(workspace),
            ],
            cwd=self.workspace_root,
            timeout_seconds=request.timeout_seconds,
            sensitive_values=[request.github_config.get("api_key", "")],
        )

    @staticmethod
    def _exclude_runner_files(workspace: Path) -> None:
        """Keep the runner's own scaffolding out of git so commit/PR modes never stage or push it.

        ``.codex-home`` holds ``auth.json`` (the ChatGPT token bundle) and the plugin cache; the
        schema file is an internal artifact. Writing them into ``.git/info/exclude`` makes git treat
        them as ignored, so ``git add -A`` / ``git status`` skip them.
        """
        exclude = workspace / ".git" / "info" / "exclude"
        try:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write("\n# Heym Codex runner scaffolding\n")
                handle.write("/.codex-home/\n")
                handle.write("/.codex-output-schema.json\n")
        except OSError:
            pass

    @staticmethod
    def _codex_home_dir(workspace: Path) -> Path:
        """CODEX_HOME lives OUTSIDE the cloned repo (a sibling dir) so its auth.json token bundle
        can never be staged or pushed by commit/PR modes, on fresh runs or resumes."""
        return Path(f"{workspace}.codex-home")

    def _authenticate(
        self,
        workspace: Path,
        codex_auth: dict,
        access_token: str,
        timeout_seconds: float,
    ) -> None:
        """Authenticate the Codex CLI for this run.

        ChatGPT-subscription credentials write ``auth.json`` directly (no per-token API cost);
        access-token credentials use ``codex login --with-access-token``.
        """
        if str((codex_auth or {}).get("auth_mode") or "").strip() == "chatgpt":
            self._write_chatgpt_auth(workspace, codex_auth)
            return
        self._codex_login(workspace, access_token, timeout_seconds)

    def _write_chatgpt_auth(self, workspace: Path, codex_auth: dict) -> None:
        codex_home = self._codex_home_dir(workspace)
        codex_home.mkdir(parents=True, exist_ok=True)
        access_token = str(codex_auth.get("access_token") or "").strip()
        id_token = str(codex_auth.get("id_token") or "").strip()
        if not access_token and not id_token:
            raise ValueError("Codex ChatGPT credential is missing tokens; re-run the sign-in")
        auth_payload = {
            # `auth_mode` is required by the codex CLI (0.142.x) to recognize a ChatGPT login.
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": id_token,
                "access_token": access_token,
                "refresh_token": str(codex_auth.get("refresh_token") or ""),
                "account_id": str(codex_auth.get("account_id") or ""),
            },
            "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        auth_path = codex_home / "auth.json"
        auth_path.write_text(json.dumps(auth_payload), encoding="utf-8")
        auth_path.chmod(0o600)

    def _codex_login(self, workspace: Path, access_token: str, timeout_seconds: float) -> None:
        codex_home = self._codex_home_dir(workspace)
        codex_home.mkdir(parents=True, exist_ok=True)
        env = self._codex_env(workspace, access_token)
        try:
            subprocess.run(
                [self.cli_command, "login", "--with-access-token"],
                input=access_token,
                text=True,
                cwd=workspace,
                env=env,
                capture_output=True,
                timeout=min(timeout_seconds, 120),
                check=True,
            )
        except FileNotFoundError as exc:
            raise ValueError("Codex CLI is not installed or not on PATH") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                self._mask_sensitive(exc.stderr or exc.stdout, [access_token])
            ) from exc

    def _run_setup_command(
        self,
        workspace: Path,
        setup_command: str,
        timeout_seconds: float,
    ) -> None:
        env = self._safe_env()
        self._run_command(
            ["/bin/sh", "-lc", setup_command],
            cwd=workspace,
            timeout_seconds=min(timeout_seconds, 600),
            env=env,
        )

    def _run_codex_exec(
        self,
        *,
        workspace: Path,
        prompt: str,
        timeout_seconds: float,
        resume_thread_id: str | None,
        codex_access_token: str,
        model: str = "",
    ) -> CodexRunResult:
        # Write the schema outside the repo (in CODEX_HOME) so it is never a git candidate.
        codex_home = self._codex_home_dir(workspace)
        codex_home.mkdir(parents=True, exist_ok=True)
        schema_path = codex_home / "output-schema.json"
        schema_path.write_text(json.dumps(CODEX_FINAL_OUTPUT_SCHEMA), encoding="utf-8")
        cmd = [self.cli_command, "exec"]
        if resume_thread_id:
            cmd.append("resume")
        if model.strip():
            cmd.extend(["--model", model.strip()])
        cmd.extend(["--json", "--output-schema", str(schema_path)])
        # `codex exec` has no --ask-for-approval flag; set the policy via config override so it
        # runs autonomously without prompting.
        cmd.extend(["-c", 'approval_policy="never"'])
        if settings.codex_network_access:
            cmd.extend(["-c", "sandbox_workspace_write.network_access=true"])
        if resume_thread_id:
            # `codex exec resume` rejects --sandbox; set the sandbox via config override instead.
            cmd.extend(["-c", 'sandbox_mode="workspace-write"'])
        else:
            cmd.extend(["--sandbox", "workspace-write"])
        # Skip the plugin/skill marketplace download — the runner uses a fresh CODEX_HOME per run,
        # so leaving it on re-clones hundreds of files every execution.
        cmd.extend(["--disable", "plugins"])
        # For resume, the positional session id precedes the prompt: `resume [OPTIONS] <ID> [PROMPT]`.
        if resume_thread_id:
            cmd.append(resume_thread_id)
        cmd.append(prompt)
        try:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                env=self._codex_env(workspace, codex_access_token),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ValueError(
                "Codex CLI is not installed or not on PATH (install '@openai/codex')"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Codex timed out after {timeout_seconds:.0f} seconds") from exc

        # codex exec reports real failures as JSONL error events on stdout; the process may still
        # exit non-zero with only status noise on stderr. Prefer the stdout error message.
        stdout_error = self._extract_exec_error(completed.stdout)
        if completed.returncode != 0 or stdout_error:
            detail = (
                stdout_error
                or self._clean_codex_stderr(completed.stderr)
                or f"Codex exec failed (exit code {completed.returncode})"
            )
            raise ValueError(self._mask_sensitive(detail, [codex_access_token]))
        return self.parser.parse(completed.stdout)

    @staticmethod
    def _extract_exec_error(stdout: str) -> str:
        """Return the last error message from codex exec JSONL events, if any."""
        message = ""
        for raw_line in (stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "error" and event.get("message"):
                message = str(event["message"]).strip()
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "error" and item.get("message"):
                message = str(item["message"]).strip()
        return message

    @staticmethod
    def _clean_codex_stderr(stderr: str) -> str:
        """Drop codex's non-error status noise (e.g. the stdin prompt) from stderr."""
        lines = [
            line
            for line in (stderr or "").splitlines()
            if line.strip() and "Reading additional input from stdin" not in line
        ]
        return "\n".join(lines).strip()

    def _finalize_result(
        self,
        result: CodexRunResult,
        workspace: Path,
        request: CodexRunRequest,
    ) -> CodexRunResult:
        result.workspace_path = str(workspace)
        result.branch_name = request.branch_name
        result.diff = self._git_output(["git", "diff", "--binary"], workspace)
        result.changed_files = self._changed_files(workspace)
        if result.status == "completed" and request.publish_mode in _CODEX_REMOTE_PUBLISH_MODES:
            self._publish(workspace, request, result)
        return result

    def _publish(
        self,
        workspace: Path,
        request: CodexRunRequest,
        result: CodexRunResult,
    ) -> None:
        """Commit and push Codex's changes according to the requested publish mode."""
        if not result.changed_files:
            return
        mode = request.publish_mode
        if mode == "direct_commit":
            # Commit straight onto the base branch that was cloned.
            self._commit_changes(workspace, request.base_branch, result, new_branch=False)
            self._push_branch(workspace, request, request.base_branch)
            result.pushed_branch = request.base_branch
            return
        if mode == "update_existing_pr":
            on_existing = self._current_branch(workspace) == request.branch_name
            self._commit_changes(workspace, request.branch_name, result, new_branch=not on_existing)
            self._push_branch(workspace, request, request.branch_name)
            result.pushed_branch = request.branch_name
            result.pull_request_url = self._open_pr_url_for_head(
                request, request.branch_name
            ) or self._create_pr(request, result, request.branch_name, draft=False)
            return

        # draft_pr / open_pr / commit_push all create and push a fresh working branch.
        self._commit_changes(workspace, request.branch_name, result, new_branch=True)
        self._push_branch(workspace, request, request.branch_name)
        result.pushed_branch = request.branch_name
        if mode == "draft_pr":
            result.pull_request_url = self._create_pr(
                request, result, request.branch_name, draft=True
            )
        elif mode == "open_pr":
            result.pull_request_url = self._create_pr(
                request, result, request.branch_name, draft=False
            )

    def _commit_changes(
        self,
        workspace: Path,
        branch: str,
        result: CodexRunResult,
        *,
        new_branch: bool,
    ) -> None:
        if new_branch:
            self._run_command(["git", "checkout", "-B", branch], cwd=workspace)
        self._run_command(["git", "add", "-A"], cwd=workspace)
        commit_cmd = [
            "git",
            "-c",
            f"user.name={settings.codex_git_author_name}",
            "-c",
            f"user.email={settings.codex_git_author_email}",
            "commit",
            "-m",
            self._commit_title(result),
        ]
        body = self._commit_body(result)
        if body and body != self._commit_title(result):
            commit_cmd.extend(["-m", body])
        self._run_command(commit_cmd, cwd=workspace)

    def _push_branch(self, workspace: Path, request: CodexRunRequest, branch: str) -> None:
        remote_url = self._clone_url_with_token(request.repository_url, request.github_config)
        self._run_command(["git", "remote", "set-url", "origin", remote_url], cwd=workspace)
        self._run_command(
            ["git", "push", "-u", "origin", branch],
            cwd=workspace,
            sensitive_values=[request.github_config.get("api_key", "")],
        )

    def _current_branch(self, workspace: Path) -> str:
        return self._git_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], workspace).strip()

    def _create_pr(
        self,
        request: CodexRunRequest,
        result: CodexRunResult,
        head: str,
        *,
        draft: bool,
    ) -> str | None:
        owner, repo = self._parse_github_owner_repo(request.repository_url)
        pr_body = str(result.pull_request_body or "").strip() or result.summary or None
        pr = GitHubService(request.github_config).create_pull_request(
            owner,
            repo,
            self._commit_title(result),
            head,
            request.base_branch,
            body=pr_body,
            draft=draft,
        )
        return str(pr.get("html_url") or "").strip() or None

    def _open_pr_url_for_head(self, request: CodexRunRequest, head: str) -> str | None:
        owner, repo = self._parse_github_owner_repo(request.repository_url)
        for pr in GitHubService(request.github_config).list_pull_requests(
            owner, repo, state="open", per_page=100
        ):
            if str((pr.get("head") or {}).get("ref") or "") == head:
                return str(pr.get("html_url") or "").strip() or None
        return None

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
                # `codex exec` appends piped stdin to the prompt; give it EOF so it never blocks
                # reading the server's stdin (git commands don't need stdin either).
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=True,
            )
        except FileNotFoundError as exc:
            binary = cmd[0] if cmd else "command"
            hint = (
                "Codex CLI is not installed or not on PATH (install '@openai/codex')"
                if binary == self.cli_command
                else f"'{binary}' is not installed or not on PATH"
            )
            raise ValueError(hint) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Command timed out after {timeout_seconds:.0f} seconds") from exc
        except subprocess.CalledProcessError as exc:
            values = [str(v) for v in (sensitive_values or []) if str(v)]
            detail = self._mask_sensitive(exc.stderr or exc.stdout or str(exc), values)
            raise ValueError(detail or "Command failed") from exc

    def _safe_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("CODEX_ACCESS_TOKEN", None)
        env.pop("OPENAI_API_KEY", None)
        return env

    @staticmethod
    def _exec_token(codex_auth: dict, access_token: str) -> str:
        """Access token to expose to ``codex exec``; empty for ChatGPT mode (uses auth.json)."""
        if str((codex_auth or {}).get("auth_mode") or "").strip() == "chatgpt":
            return ""
        return access_token

    def _codex_env(self, workspace: Path, access_token: str) -> dict[str, str]:
        env = self._safe_env()
        env["CODEX_HOME"] = str(self._codex_home_dir(workspace))
        if access_token:
            env["CODEX_ACCESS_TOKEN"] = access_token
        return env

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

    def cleanup_workspace(self, workspace_path: str | None) -> None:
        if not workspace_path:
            return
        path = Path(workspace_path).resolve()
        root = self.workspace_root.resolve()
        if path == root or root not in path.parents:
            return
        shutil.rmtree(path, ignore_errors=True)
        # Remove the external CODEX_HOME sibling (holds the token bundle) as well.
        shutil.rmtree(self._codex_home_dir(path), ignore_errors=True)

    @staticmethod
    def _build_prompt(task_prompt: str) -> str:
        return (
            "You are running as the Heym Codex node inside a local cloned git repository.\n"
            f"{_CODEX_LOCAL_ONLY_RULES}\n"
            "If you need missing requirements, secrets, or a product decision, return "
            "`status: needs_input` with one concise question. Otherwise implement the task "
            "and return `status: completed` with a summary and validation notes. Always set "
            "`pull_request_title` to a concise, complete one-line change description "
            "(imperative mood, ideally <=72 characters) suitable as a commit subject.\n\n"
            f"Task:\n{task_prompt}"
        )

    @staticmethod
    def _build_resume_prompt(answer_text: str) -> str:
        return (
            "The user answered your previous follow-up question. Continue the same task.\n"
            f"{_CODEX_LOCAL_ONLY_RULES}\n"
            "Return `needs_input` only if one more user decision is truly essential.\n\n"
            f"Answer:\n{answer_text}"
        )

    @staticmethod
    def _commit_title(result: CodexRunResult) -> str:
        # Prefer Codex's dedicated pull_request_title — a concise, complete one-line subject.
        title = re.sub(r"\s+", " ", str(result.pull_request_title or "")).strip()
        if title:
            return title
        summary = re.sub(r"\s+", " ", result.summary).strip()
        if not summary:
            return "Apply Codex changes"
        # Fall back to the full first sentence of the summary (no length cap — GitHub itself
        # elides overly long subjects in list views while keeping the complete text).
        return re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0]

    @staticmethod
    def _commit_body(result: CodexRunResult) -> str:
        """Full commit body so the message is not lost when the subject is truncated to 72 chars."""
        parts: list[str] = []
        summary = str(result.summary or "").strip()
        if summary:
            parts.append(summary)
        validation = str(result.validation or "").strip()
        if validation:
            parts.append(f"Validation:\n{validation}")
        return "\n\n".join(parts)

    @staticmethod
    def _clone_url_with_token(repository_url: str, github_config: dict) -> str:
        token = str(github_config.get("api_key") or "").strip()
        if not token:
            return repository_url
        parsed = urlparse(repository_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return repository_url
        if "@" in parsed.netloc:
            return repository_url
        netloc = f"x-access-token:{quote(token, safe='')}@{parsed.netloc}"
        return urlunparse(parsed._replace(netloc=netloc))

    @staticmethod
    def _parse_github_owner_repo(repository_url: str) -> tuple[str, str]:
        parsed = urlparse(repository_url)
        path = parsed.path.removesuffix(".git").strip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Repository URL must include owner and repository")
        return parts[-2], parts[-1]

    @staticmethod
    def _mask_sensitive(text: str, values: list[object]) -> str:
        masked = text
        for value in values:
            secret = str(value or "")
            if secret:
                masked = masked.replace(secret, "[masked]")
        return masked
